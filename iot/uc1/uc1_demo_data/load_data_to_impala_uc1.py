#!/usr/bin/env python3
"""
Load UC1 Predictive Maintenance CSV data into Impala (Cloudera Data Warehouse).

Loads three CSV files into iot_uc1_db:
  vibration_readings.csv  →  vibration_readings
  machine_health.csv      →  machine_health
  rul_predictions.csv     →  rul_predictions

Run create_impala_tables_uc1.py first.

Usage:
    python load_data_to_impala_uc1.py
    python load_data_to_impala_uc1.py --host <host> --user <user> --password <pwd>
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
DATABASE    = 'iot_uc1_db'

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


def _int(v):
    v = v.strip() if v else ""
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def _bool(v):
    v = v.strip().lower() if v else ""
    if v in ("true", "1", "yes"):
        return True
    if v in ("false", "0", "no"):
        return False
    return None


def parse_vibration_row(row):
    return (
        _str(row["event_time"]),
        _str(row["machine_id"]),
        _str(row["axis"]),
        _dec(row["vibration_rms"]),
        _dec(row["vibration_peak"]),
        _str(row["unit"]),
    )


def parse_health_row(row):
    return (
        _str(row["event_time"]),
        _str(row["machine_id"]),
        _dec(row["health_score"]),
        _dec(row["anomaly_score"]),
        _bool(row["edge_alert_flag"]),
        _dec(row["vibration_rms_x"]),
        _dec(row["vibration_rms_y"]),
        _dec(row["vibration_rms_z"]),
        _int(row["window_minutes"]),
    )


def parse_rul_row(row):
    return (
        _str(row["prediction_time"]),
        _str(row["machine_id"]),
        _dec(row["rul_hours"]),
        _dec(row["confidence"]),
        _str(row["risk_level"]),
        _str(row["feature_window"]),
    )


VIBRATION_INSERT = "INSERT INTO vibration_readings VALUES (?,?,?,?,?,?)"
HEALTH_INSERT = "INSERT INTO machine_health VALUES (?,?,?,?,?,?,?,?,?)"
RUL_INSERT = "INSERT INTO rul_predictions VALUES (?,?,?,?,?,?)"

LOAD_PLAN = [
    ("vibration_readings.csv", "vibration_readings", VIBRATION_INSERT, parse_vibration_row),
    ("machine_health.csv", "machine_health", HEALTH_INSERT, parse_health_row),
    ("rul_predictions.csv", "rul_predictions", RUL_INSERT, parse_rul_row),
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

    print("\nM02 CRITICAL alert (expected health_score < 40 at 14:30):")
    cursor.execute("""
        SELECT machine_id, event_time, health_score, vibration_rms_z, anomaly_score
        FROM machine_health
        WHERE machine_id = 'M02' AND event_time = '2025-06-24 14:30:00'
    """)
    for row in cursor.fetchall():
        print(f"  {row[0]}  {row[1]}  health={row[2]}  z_rms={row[3]}  anomaly={row[4]}")

    print("\nM03 edge anomaly window:")
    cursor.execute("""
        SELECT machine_id, event_time, edge_alert_flag, anomaly_score
        FROM machine_health
        WHERE machine_id = 'M03' AND edge_alert_flag = true
        LIMIT 3
    """)
    for row in cursor.fetchall():
        print(f"  {row[0]}  {row[1]}  edge_flag={row[2]}  anomaly={row[3]}")


def main():
    args = parse_args()
    print("=" * 70)
    print("UC1 — Load CSV Data into Impala")
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
    p = argparse.ArgumentParser(description="Load UC1 demo CSVs into iot_uc1_db")
    p.add_argument("--host", default=IMPALA_HOST)
    p.add_argument("--port", type=int, default=IMPALA_PORT)
    p.add_argument("--user", default=USERNAME)
    p.add_argument("--password", default=PASSWORD)
    return p.parse_args()


if __name__ == "__main__":
    main()
