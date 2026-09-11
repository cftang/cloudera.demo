#!/usr/bin/env python3
"""
Load UC2 Predictive Quality Management CSV data into Impala (Cloudera Data Warehouse).

Loads three CSV files into iot_uc2_db:
  sensor_readings.csv       →  sensor_readings
  quality_events.csv        →  quality_events
  quality_predictions.csv   →  quality_predictions

Run create_impala_tables_uc2.py first.

Usage:
    python load_data_to_impala_uc2.py
    python load_data_to_impala_uc2.py --host <host> --user <user> --password <pwd>
"""

import argparse
import csv
import os
import sys
from decimal import Decimal, InvalidOperation
from impala.dbapi import connect

IMPALA_HOST = '<your-impala-host>'
IMPALA_PORT = 443
USERNAME    = '<your-username>'
PASSWORD    = '<your-workload-password>'
DATABASE    = 'iot_uc2_db'

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
BATCH_SIZE = 50


def _str(v):
    v = v.strip() if v else ""
    return v if v else None


def _dec(v):
    v = v.strip() if v else ""
    if not v:
        return None
    try:
        return float(Decimal(v))
    except InvalidOperation:
        return None


def parse_sensor_row(row):
    return (
        _str(row["event_time"]),
        _str(row["machine_id"]),
        _str(row["process_type"]),
        _str(row["metric"]),
        _dec(row["value"]),
        _str(row["unit"]),
    )


def parse_event_row(row):
    return (
        _str(row["event_time"]),
        _str(row["machine_id"]),
        _str(row["work_order_id"]),
        _str(row["event_type"]),
        _str(row["defect_code"]) or None,
        _str(row["operator_id"]),
        _str(row["raw_payload"]),
    )


def parse_prediction_row(row):
    return (
        _str(row["prediction_time"]),
        _str(row["machine_id"]),
        _str(row["work_order_id"]),
        _dec(row["defect_rate"]),
        _str(row["risk_level"]),
        _dec(row["confidence"]),
        _str(row["feature_window"]),
    )


SENSOR_INSERT = "INSERT INTO sensor_readings VALUES (?,?,?,?,?,?)"
EVENT_INSERT = "INSERT INTO quality_events VALUES (?,?,?,?,?,?,?)"
PREDICTION_INSERT = "INSERT INTO quality_predictions VALUES (?,?,?,?,?,?,?)"

LOAD_PLAN = [
    ("sensor_readings.csv", "sensor_readings", SENSOR_INSERT, parse_sensor_row),
    ("quality_events.csv", "quality_events", EVENT_INSERT, parse_event_row),
    ("quality_predictions.csv", "quality_predictions", PREDICTION_INSERT, parse_prediction_row),
]


def connect_to_impala(host, port, user, password):
    configs = [
        {
            "host": host, "port": port, "database": DATABASE,
            "user": user, "password": password, "timeout": 120,
            "use_ssl": True, "auth_mechanism": "LDAP",
            "use_http_transport": True, "http_path": "cliservice",
        },
        {
            "host": host, "port": port, "database": DATABASE,
            "user": user, "password": password, "timeout": 120,
            "use_ssl": True, "auth_mechanism": "PLAIN",
            "use_http_transport": True, "http_path": "cliservice",
        },
    ]
    for i, cfg in enumerate(configs, 1):
        try:
            print(f"  Trying config {i}...")
            conn = connect(**cfg)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            print(f"  Connected with config {i}\n")
            return conn, cursor
        except Exception as e:
            print(f"  Failed: {str(e)[:120]}")
    return None, None


def load_csv(cursor, csv_filename, table_name, insert_sql, row_parser):
    csv_path = os.path.join(DATA_DIR, csv_filename)
    if not os.path.exists(csv_path):
        print(f"  CSV not found: {csv_path}")
        return 0

    rows = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for line_num, row in enumerate(csv.DictReader(fh), start=2):
            try:
                rows.append(row_parser(row))
            except Exception as e:
                print(f"    Skipping line {line_num}: {e}")

    print(f"  Parsed {len(rows)} rows → {table_name}")
    inserted = 0
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        try:
            cursor.executemany(insert_sql, batch)
            inserted += len(batch)
        except Exception:
            for row_tuple in batch:
                try:
                    cursor.execute(insert_sql, row_tuple)
                    inserted += 1
                except Exception as row_err:
                    print(f"    Row error: {row_err}")
    print(f"  Inserted {inserted} rows")
    return inserted


def verify(cursor):
    print("\n" + "=" * 70)
    print("Post-load verification")
    print("=" * 70)
    for _, table, _, _ in LOAD_PLAN:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"  {table:<25} {cursor.fetchone()[0]:>6} rows")

    print("\nFrame Welding Crisis — HIGH risk predictions (CNC-01):")
    cursor.execute("""
        SELECT machine_id, prediction_time, defect_rate, risk_level, confidence
        FROM quality_predictions
        WHERE machine_id = 'CNC-01' AND risk_level = 'HIGH'
        LIMIT 5
    """)
    for row in cursor.fetchall():
        print(f"  {row[0]}  {row[1]}  defect_rate={row[2]}  risk={row[3]}  conf={row[4]}")

    print("\nPaint Booth — MEDIUM risk (PAINT-01 afternoon):")
    cursor.execute("""
        SELECT machine_id, prediction_time, defect_rate, risk_level
        FROM quality_predictions
        WHERE machine_id = 'PAINT-01' AND risk_level = 'MEDIUM'
        LIMIT 3
    """)
    for row in cursor.fetchall():
        print(f"  {row[0]}  {row[1]}  defect_rate={row[2]}  risk={row[3]}")

    print("\nBattery Anomaly — INVESTIGATE (BAT-01):")
    cursor.execute("""
        SELECT machine_id, prediction_time, defect_rate, risk_level, feature_window
        FROM quality_predictions
        WHERE machine_id = 'BAT-01' AND risk_level = 'INVESTIGATE'
        LIMIT 3
    """)
    for row in cursor.fetchall():
        print(f"  {row[0]}  {row[1]}  defect_rate={row[2]}  risk={row[3]}")


def main():
    args = parse_args()
    print("=" * 70)
    print("UC2 — Load CSV Data into Impala")
    print("=" * 70)
    print(f"Host     : {args.host}:{args.port}")
    print(f"Database : {DATABASE}")
    print(f"Data dir : {DATA_DIR}\n")

    conn, cursor = connect_to_impala(args.host, args.port, args.user, args.password)
    if not conn:
        sys.exit(1)

    try:
        cursor.execute(f"USE {DATABASE}")
        for csv_file, table, insert_sql, parser in LOAD_PLAN:
            print("-" * 70)
            print(f"Loading {csv_file} → {table}")
            cursor.execute(f"TRUNCATE TABLE {table}")
            load_csv(cursor, csv_file, table, insert_sql, parser)
        verify(cursor)
        print("\nAll tables loaded.")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        cursor.close()
        conn.close()


def parse_args():
    p = argparse.ArgumentParser(description="Load UC2 demo CSVs into iot_uc2_db")
    p.add_argument("--host", default=IMPALA_HOST)
    p.add_argument("--port", type=int, default=IMPALA_PORT)
    p.add_argument("--user", default=USERNAME)
    p.add_argument("--password", default=PASSWORD)
    return p.parse_args()


if __name__ == "__main__":
    main()
