#!/usr/bin/env python3
"""
Create UC2 Predictive Quality Management tables in Impala (Cloudera Data Warehouse).

Creates three Iceberg tables in iot_uc2_db:
  - sensor_readings
  - quality_events
  - quality_predictions

Usage:
    python create_impala_tables_uc2.py
    python create_impala_tables_uc2.py --host <host> --user <user> --password <pwd>
"""

import argparse
import sys
import time

IMPALA_HOST = '<your-impala-host>'
IMPALA_PORT = 443
USERNAME    = '<your-username>'
PASSWORD    = '<your-workload-password>'
DATABASE    = 'iot_uc2_db'

DDL_STATEMENTS = [
    f"CREATE DATABASE IF NOT EXISTS {DATABASE}",
    f"USE {DATABASE}",
    "DROP TABLE IF EXISTS sensor_readings",
    """CREATE TABLE sensor_readings (
    event_time     TIMESTAMP,
    machine_id     STRING,
    process_type   STRING,
    metric         STRING,
    value          DOUBLE,
    unit           STRING
)
COMMENT 'UC2 time-series sensor readings from CNC, paint booth, and battery assembly'
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
COMMENT 'UC2 quality events from MES and document store via NiFi CDC'
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
COMMENT 'UC2 quality prediction model output — defect rate and risk level'
STORED BY ICEBERG""",
]

VERIFY_TABLES = ["sensor_readings", "quality_events", "quality_predictions"]


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
    print("UC2 — Create Iceberg Tables")
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
        print("Next step: python load_data_to_impala_uc2.py")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        cursor.close()
        conn.close()


def parse_args():
    p = argparse.ArgumentParser(description="Create iot_uc2_db Iceberg tables")
    p.add_argument("--host", default=IMPALA_HOST)
    p.add_argument("--port", type=int, default=IMPALA_PORT)
    p.add_argument("--user", default=USERNAME)
    p.add_argument("--password", default=PASSWORD)
    return p.parse_args()


if __name__ == "__main__":
    run_ddl(parse_args())
