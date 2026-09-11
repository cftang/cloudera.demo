#!/usr/bin/env python3
"""
Create UC1 Predictive Maintenance tables in Impala (Cloudera Data Warehouse).

Creates three Iceberg tables in iot_uc1_db:
  - vibration_readings
  - machine_health
  - rul_predictions

Usage:
    python create_impala_tables_uc1.py
    python create_impala_tables_uc1.py --host <host> --user <user> --password <pwd>
"""

import argparse
import sys
import time

IMPALA_HOST = '<your-impala-host>'
IMPALA_PORT = 443
USERNAME    = '<your-username>'
PASSWORD    = '<your-workload-password>'
DATABASE    = 'iot_uc1_db'

DDL_STATEMENTS = [
    f"CREATE DATABASE IF NOT EXISTS {DATABASE}",
    f"USE {DATABASE}",
    "DROP TABLE IF EXISTS vibration_readings",
    """CREATE TABLE vibration_readings (
    event_time      TIMESTAMP,
    machine_id      STRING,
    axis            STRING,
    vibration_rms   DOUBLE,
    vibration_peak  DOUBLE,
    unit            STRING
)
COMMENT 'UC1 raw 3-axis vibration telemetry from CNC machines M01-M03'
STORED BY ICEBERG""",
    "DROP TABLE IF EXISTS machine_health",
    """CREATE TABLE machine_health (
    event_time          TIMESTAMP,
    machine_id          STRING,
    health_score        DOUBLE,
    anomaly_score       DOUBLE,
    edge_alert_flag     BOOLEAN,
    vibration_rms_x     DOUBLE,
    vibration_rms_y     DOUBLE,
    vibration_rms_z     DOUBLE,
    window_minutes      INT
)
COMMENT 'UC1 rolling-window health scores and edge anomaly flags'
STORED BY ICEBERG""",
    "DROP TABLE IF EXISTS rul_predictions",
    """CREATE TABLE rul_predictions (
    prediction_time TIMESTAMP,
    machine_id      STRING,
    rul_hours         DOUBLE,
    confidence        DOUBLE,
    risk_level        STRING,
    feature_window    STRING
)
COMMENT 'UC1 RUL model output — remaining useful life predictions'
STORED BY ICEBERG""",
]

VERIFY_TABLES = ["vibration_readings", "machine_health", "rul_predictions"]


def connect_impala(host, port, user, password, database=DATABASE):
    from impala.dbapi import connect
    configs = [
        {
            "host": host, "port": port, "database": database,
            "user": user, "password": password, "timeout": 120,
            "use_ssl": True, "auth_mechanism": "LDAP",
            "use_http_transport": True,
            "http_path": "cliservice",
        },
        {
            "host": host, "port": port, "database": database,
            "user": user, "password": password, "timeout": 120,
            "use_ssl": True, "auth_mechanism": "PLAIN",
            "use_http_transport": True,
            "http_path": "cliservice",
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
    print("UC1 — Create Iceberg Tables")
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
        print("Next step: python load_data_to_impala_uc1.py")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        cursor.close()
        conn.close()


def parse_args():
    p = argparse.ArgumentParser(description="Create iot_uc1_db Iceberg tables")
    p.add_argument("--host", default=IMPALA_HOST)
    p.add_argument("--port", type=int, default=IMPALA_PORT)
    p.add_argument("--user", default=USERNAME)
    p.add_argument("--password", default=PASSWORD)
    return p.parse_args()


if __name__ == "__main__":
    run_ddl(parse_args())
