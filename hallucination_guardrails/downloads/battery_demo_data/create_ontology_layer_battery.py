#!/usr/bin/env python3
"""
Create the ontology / semantic layer for Story 01 (Battery Pack) in Impala.

This is the physical governed layer the ontology-grounding-tool's query_plan targets
(Lab 04 Step 2, hallucination_guardrails). The TBox/ABox structural split lives in Impala
here; the ontology *semantic* layer (aliases, glossary) is the config-driven tool. Together
they are the "prevent-first" thesis: the agent can only ask the governed views for things
the ontology defines.

Adds to iot_car_battery_db (on top of create_impala_tables_battery.py's seven tables):
  dim tables (reference / TBox vocabulary)
    - dim_alloy          material_grade -> alloy_family / material_class
    - dim_defect_code    defect_code    -> defect_name / defect_category
    - dim_status         status         -> is_citable (only RELEASED is citable evidence)
    - dim_relation_type  relation_type  -> human description
  governed views (what the query_plan SELECTs)
    - v_part_semantic            unified_part_metadata + resolved material_grade (from the
                                 tech_specs JSON) + dim_alloy, filtered status='RELEASED'
    - v_quality_events_semantic  quality_events + module_id/cell_lot (from raw_payload JSON)
                                 + dim_defect_code

material_grade lives inside the tech_specs JSON string, and module_id/cell_lot inside the
raw_payload JSON string, so both views resolve them with get_json_object(...).

Usage:
    python create_ontology_layer_battery.py --print-sql          # dry-run: print DDL only
    python create_ontology_layer_battery.py                      # execute against Impala
    python create_ontology_layer_battery.py --host <h> --user <u> --password <p>
"""

import argparse
import sys
import time

IMPALA_HOST = '<your-impala-host>'
IMPALA_PORT = 443
USERNAME    = '<your-username>'
PASSWORD    = '<your-workload-password>'
DATABASE    = 'iot_car_battery_db'

DDL_STATEMENTS = [
    f"CREATE DATABASE IF NOT EXISTS {DATABASE}",
    f"USE {DATABASE}",

    # Views depend on the dim tables — drop views first.
    "DROP VIEW IF EXISTS v_part_semantic",
    "DROP VIEW IF EXISTS v_quality_events_semantic",

    # --- dim_alloy: material_grade -> alloy family / class -------------------------------
    "DROP TABLE IF EXISTS dim_alloy",
    """CREATE TABLE dim_alloy (
    material_grade STRING,
    alloy_family   STRING,
    material_class STRING
)
COMMENT 'Ontology dim: canonical material grade -> alloy family / material class'
STORED BY ICEBERG""",
    """INSERT INTO dim_alloy VALUES
    ('6061-T6',       'aluminum', 'metal'),
    ('steel-Q345',    'steel',    'metal'),
    ('PA66-GF30',     'polymer',  'plastic'),
    ('copper-C11000', 'copper',   'metal')""",

    # --- dim_defect_code: defect_code -> name / category ---------------------------------
    "DROP TABLE IF EXISTS dim_defect_code",
    """CREATE TABLE dim_defect_code (
    defect_code     STRING,
    defect_name     STRING,
    defect_category STRING
)
COMMENT 'Ontology dim: canonical defect code -> human name / category'
STORED BY ICEBERG""",
    """INSERT INTO dim_defect_code VALUES
    ('THM-042',   'Thermal anomaly / over-temperature', 'thermal'),
    ('DCR-019',   'DC resistance out of specification',  'electrical'),
    ('DIM-004',   'Dimensional deviation',               'dimensional'),
    ('PRESS-004', 'Press-fit force out of range',        'assembly')""",

    # --- dim_status: status -> is_citable ------------------------------------------------
    "DROP TABLE IF EXISTS dim_status",
    """CREATE TABLE dim_status (
    status     STRING,
    is_citable BOOLEAN
)
COMMENT 'Ontology dim: lifecycle status -> whether the entity may be cited as evidence'
STORED BY ICEBERG""",
    """INSERT INTO dim_status VALUES
    ('RELEASED',  TRUE),
    ('IN_REVIEW', FALSE),
    ('WIP',       FALSE),
    ('OBSOLETE',  FALSE)""",

    # --- dim_relation_type: relation_type -> description ---------------------------------
    "DROP TABLE IF EXISTS dim_relation_type",
    """CREATE TABLE dim_relation_type (
    relation_type STRING,
    description   STRING
)
COMMENT 'Ontology dim: component_doc_map.relation_type vocabulary'
STORED BY ICEBERG""",
    """INSERT INTO dim_relation_type VALUES
    ('disposition_guide',  'Disposition / rework guidance (SOP)'),
    ('incoming_coa',       'Incoming certificate of analysis'),
    ('supplier_ecn',       'Supplier engineering change notice'),
    ('quality_sop',        'Quality standard operating procedure'),
    ('engineering_drawing','Released engineering drawing'),
    ('reference',          'Generic / reference material')""",

    # --- v_part_semantic: governed part view ---------------------------------------------
    # material_grade resolved from the tech_specs JSON; joined to dim_alloy; RELEASED only.
    """CREATE VIEW v_part_semantic AS
SELECT
    p.part_number,
    p.object_name,
    p.part_type,
    p.version,
    p.status,
    get_json_object(p.tech_specs, '$.material_grade')                 AS material_grade,
    a.alloy_family,
    a.material_class,
    get_json_object(p.tech_specs, '$.surface_treatment')             AS surface_treatment,
    CAST(get_json_object(p.tech_specs, '$.max_operating_temp_c') AS DOUBLE) AS max_operating_temp_c,
    CAST(get_json_object(p.tech_specs, '$.weight_kg') AS DOUBLE)      AS weight_kg
FROM unified_part_metadata p
LEFT JOIN dim_alloy a
    ON get_json_object(p.tech_specs, '$.material_grade') = a.material_grade
WHERE p.status = 'RELEASED'""",

    # --- v_quality_events_semantic: governed quality-events view -------------------------
    # module_id / cell_lot resolved from raw_payload JSON; defect enriched via dim_defect_code.
    """CREATE VIEW v_quality_events_semantic AS
SELECT
    q.event_time,
    q.machine_id,
    q.work_order_id,
    get_json_object(q.raw_payload, '$.module_id') AS module_id,
    get_json_object(q.raw_payload, '$.cell_lot')  AS cell_lot,
    q.defect_code,
    d.defect_name,
    d.defect_category
FROM quality_events q
LEFT JOIN dim_defect_code d
    ON q.defect_code = d.defect_code""",
]

VERIFY_TABLES = ["dim_alloy", "dim_defect_code", "dim_status", "dim_relation_type"]
VERIFY_VIEWS = ["v_part_semantic", "v_quality_events_semantic"]


def connect_impala(host, port, user, password, database=DATABASE):
    from impala.dbapi import connect
    configs = [
        {
            "host": host, "port": port, "database": database,
            "user": user, "password": password, "timeout": 120,
            "use_ssl": True, "auth_mechanism": "LDAP",
            "use_http_transport": True, "http_path": "cliservice",
        },
        {
            "host": host, "port": port, "database": database,
            "user": user, "password": password, "timeout": 120,
            "use_ssl": True, "auth_mechanism": "PLAIN",
            "use_http_transport": True, "http_path": "cliservice",
        },
    ]
    for i, cfg in enumerate(configs, 1):
        try:
            print(f"  Trying config {i} (auth={cfg['auth_mechanism']})...")
            conn = connect(**cfg)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            print(f"  Connected with config {i}\n")
            return conn, cursor
        except Exception as e:
            print(f"  Failed: {str(e)[:120]}")
    return None, None


def print_sql():
    print("=" * 70)
    print("Story01 Battery Pack — Ontology / Semantic Layer DDL (dry-run)")
    print("=" * 70)
    for stmt in DDL_STATEMENTS:
        print(f"\n{stmt.strip()};")


def run_ddl(args):
    print("=" * 70)
    print("Story01 Battery Pack — Create Ontology / Semantic Layer")
    print("=" * 70)
    print(f"Host     : {args.host}:{args.port}")
    print(f"User     : {args.user}")
    print(f"Database : {DATABASE}\n")

    conn, cursor = connect_impala(args.host, args.port, args.user, args.password)
    if not conn:
        print("All connection attempts failed.")
        sys.exit(1)

    try:
        for stmt in DDL_STATEMENTS:
            preview = stmt.strip().splitlines()[0][:60]
            t0 = time.monotonic()
            cursor.execute(stmt)
            elapsed = (time.monotonic() - t0) * 1000
            print(f"  OK  {preview}  ({elapsed:.0f} ms)")

        print("\n" + "=" * 70)
        print("Verification")
        print("=" * 70)
        cursor.execute(f"USE {DATABASE}")
        for table in VERIFY_TABLES:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            n = cursor.fetchone()[0]
            print(f"  {table:<28} {n} rows")
        for view in VERIFY_VIEWS:
            cursor.execute(f"SELECT COUNT(*) FROM {view}")
            n = cursor.fetchone()[0]
            print(f"  {view:<28} {n} rows (RELEASED-only for v_part_semantic)")

        print("\nOntology layer created.")
        print("Next: the ontology-grounding-tool emits SELECTs against these views (Lab 04 Step 2).")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        cursor.close()
        conn.close()


def parse_args():
    p = argparse.ArgumentParser(description="Create iot_car_battery_db ontology / semantic layer")
    p.add_argument("--host", default=IMPALA_HOST)
    p.add_argument("--port", type=int, default=IMPALA_PORT)
    p.add_argument("--user", default=USERNAME)
    p.add_argument("--password", default=PASSWORD)
    p.add_argument("--print-sql", action="store_true",
                   help="Print the generated DDL and exit (no Impala connection).")
    return p.parse_args()


if __name__ == "__main__":
    a = parse_args()
    if a.print_sql:
        print_sql()
    else:
        run_ddl(a)
