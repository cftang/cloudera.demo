#!/usr/bin/env python3
"""
Create Story 01 (Battery Pack Assembly) tables in Impala (Cloudera Data Warehouse).

Creates seven Iceberg tables + one view in iot_car_battery_db:
  - sensor_readings        (narrow time series — 5-Agent story)
  - quality_events         (work-order events; raw_payload carries cell_lot)
  - quality_predictions    (ML model output)
  - module_eol_test        (per-module End-of-Line test — refined 3-Agent story)
  - module_eol_test_v      (VIEW over module_eol_test, referenced by the PDF SQL)
  - unified_part_metadata  (3D part catalog; nested attrs as JSON strings)
  - document_metadata      (SOP / COA / ECN knowledge sources)
  - component_doc_map       (component_id ↔ doc_id bridge)

Note: unified_part_metadata stores tech_specs / bom_hierarchy / data_lineage as JSON
STRING columns (query via get_json_object). The lab prose shows an illustrative
STRUCT/LIST DDL; JSON strings keep the table CSV-loadable while all demo JOINs (which
only touch the flat columns part_number/object_name/storage_url/viewer_url) still work.

Usage:
    python create_impala_tables_battery.py
    python create_impala_tables_battery.py --host <host> --user <user> --password <pwd>
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

    "DROP VIEW IF EXISTS module_eol_test_v",

    "DROP TABLE IF EXISTS sensor_readings",
    """CREATE TABLE sensor_readings (
    event_time     TIMESTAMP,
    machine_id     STRING,
    process_type   STRING,
    metric         STRING,
    value          DOUBLE,
    unit           STRING
)
COMMENT 'Story01 narrow time-series sensor readings — battery module assembly'
STORED BY ICEBERG""",

    "DROP TABLE IF EXISTS quality_events",
    """CREATE TABLE quality_events (
    event_time     TIMESTAMP,
    machine_id     STRING,
    work_order_id  STRING,
    event_type     STRING,
    defect_code    STRING,
    operator_id    STRING,
    raw_payload    STRING
)
COMMENT 'Story01 quality events; raw_payload JSON carries cell_lot and module_id'
STORED BY ICEBERG""",

    "DROP TABLE IF EXISTS quality_predictions",
    """CREATE TABLE quality_predictions (
    prediction_time TIMESTAMP,
    machine_id      STRING,
    work_order_id   STRING,
    defect_rate     DOUBLE,
    risk_level      STRING,
    confidence      DOUBLE,
    feature_window  STRING
)
COMMENT 'Story01 quality prediction model output — defect rate and risk level'
STORED BY ICEBERG""",

    "DROP TABLE IF EXISTS module_eol_test",
    """CREATE TABLE module_eol_test (
    test_id           STRING,
    module_id         STRING,
    machine_id        STRING,
    cell_lot          STRING,
    test_date         STRING,
    temperature_delta DOUBLE,
    voltage_std       DOUBLE,
    dcr               DOUBLE,
    is_anomaly        INT,
    anomaly_type      STRING
)
COMMENT 'Story01 per-module End-of-Line test results — batch anomaly-rate narrative'
STORED BY ICEBERG""",

    "DROP TABLE IF EXISTS unified_part_metadata",
    """CREATE TABLE unified_part_metadata (
    part_number    STRING,
    object_name    STRING,
    part_type      STRING,
    version        STRING,
    status         STRING,
    source_type    STRING,
    storage_url    STRING,
    viewer_url     STRING,
    created_date   STRING,
    modified_date  STRING,
    tech_specs     STRING,
    bom_hierarchy  STRING,
    data_lineage   STRING
)
COMMENT 'Story01 unified 3D part catalog; nested attrs as JSON strings'
STORED BY ICEBERG""",

    "DROP TABLE IF EXISTS document_metadata",
    """CREATE TABLE document_metadata (
    doc_id         STRING,
    title          STRING,
    source_type    STRING,
    uri            STRING,
    ocr_processed  BOOLEAN,
    created_date   STRING,
    tags           STRING,
    summary        STRING
)
COMMENT 'Story01 document metadata — SOP / COA / ECN knowledge sources'
STORED BY ICEBERG""",

    "DROP TABLE IF EXISTS component_doc_map",
    """CREATE TABLE component_doc_map (
    doc_id         STRING,
    component_id   STRING,
    relation_type  STRING
)
COMMENT 'Story01 component_id <-> doc_id bridge table'
STORED BY ICEBERG""",

    # View so the refined-story SQL (FROM module_eol_test_v) resolves unchanged.
    "CREATE VIEW module_eol_test_v AS SELECT * FROM module_eol_test",
]

VERIFY_TABLES = [
    "sensor_readings", "quality_events", "quality_predictions", "module_eol_test",
    "unified_part_metadata", "document_metadata", "component_doc_map",
]


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


def run_ddl(args):
    print("=" * 70)
    print("Story01 Battery Pack — Create Iceberg Tables")
    print("=" * 70)
    print(f"Host     : {args.host}:{args.port}")
    print(f"User     : {args.user}")
    print(f"Database : {DATABASE}\n")

    # Bootstrap against an always-present DB: iot_car_battery_db doesn't exist yet on the first
    # run, and connecting straight into it makes impyla issue `USE iot_car_battery_db` at connect
    # time, which fails before the CREATE DATABASE DDL can run. The DDL below CREATEs + USEs it.
    conn, cursor = connect_impala(args.host, args.port, args.user, args.password, database="default")
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
        print("Table verification")
        print("=" * 70)
        cursor.execute(f"USE {DATABASE}")
        for table in VERIFY_TABLES:
            cursor.execute(f"DESCRIBE {table}")
            cols = cursor.fetchall()
            print(f"\n{table} ({len(cols)} columns)")
            for col in cols:
                print(f"  {col[0]:<25} {col[1]}")

        print("\nAll tables created.")
        print("Next step: python load_data_to_impala_battery.py")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        cursor.close()
        conn.close()


def parse_args():
    p = argparse.ArgumentParser(description="Create iot_car_battery_db Iceberg tables")
    p.add_argument("--host", default=IMPALA_HOST)
    p.add_argument("--port", type=int, default=IMPALA_PORT)
    p.add_argument("--user", default=USERNAME)
    p.add_argument("--password", default=PASSWORD)
    return p.parse_args()


if __name__ == "__main__":
    run_ddl(parse_args())
