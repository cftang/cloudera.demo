#!/usr/bin/env python3
"""
Load Story 01 (Battery Pack Assembly) CSV data into Impala (Cloudera Data Warehouse).

Loads seven CSV files into iot_car_battery_db:
  sensor_readings.csv        →  sensor_readings
  quality_events.csv         →  quality_events
  quality_predictions.csv    →  quality_predictions
  module_eol_test.csv        →  module_eol_test
  unified_part_metadata.csv  →  unified_part_metadata
  document_metadata.csv      →  document_metadata
  component_doc_map.csv      →  component_doc_map

Run create_impala_tables_battery.py first.

Usage:
    python load_data_to_impala_battery.py
    python load_data_to_impala_battery.py --host <host> --user <user> --password <pwd>
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
DATABASE    = 'iot_car_battery_db'

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
    if v in ("true", "1", "t", "yes"):
        return True
    if v in ("false", "0", "f", "no"):
        return False
    return None


def parse_sensor_row(row):
    return (_str(row["event_time"]), _str(row["machine_id"]), _str(row["process_type"]),
            _str(row["metric"]), _dec(row["value"]), _str(row["unit"]))


def parse_event_row(row):
    return (_str(row["event_time"]), _str(row["machine_id"]), _str(row["work_order_id"]),
            _str(row["event_type"]), _str(row["defect_code"]), _str(row["operator_id"]),
            _str(row["raw_payload"]))


def parse_prediction_row(row):
    return (_str(row["prediction_time"]), _str(row["machine_id"]), _str(row["work_order_id"]),
            _dec(row["defect_rate"]), _str(row["risk_level"]), _dec(row["confidence"]),
            _str(row["feature_window"]))


def parse_eol_row(row):
    return (_str(row["test_id"]), _str(row["module_id"]), _str(row["machine_id"]),
            _str(row["cell_lot"]), _str(row["test_date"]), _dec(row["temperature_delta"]),
            _dec(row["voltage_std"]), _dec(row["dcr"]), _int(row["is_anomaly"]),
            _str(row["anomaly_type"]))


def parse_part_row(row):
    return (_str(row["part_number"]), _str(row["object_name"]), _str(row["part_type"]),
            _str(row["version"]), _str(row["status"]), _str(row["source_type"]),
            _str(row["storage_url"]), _str(row["viewer_url"]), _str(row["created_date"]),
            _str(row["modified_date"]), _str(row["tech_specs"]), _str(row["bom_hierarchy"]),
            _str(row["data_lineage"]))


def parse_doc_row(row):
    return (_str(row["doc_id"]), _str(row["title"]), _str(row["source_type"]),
            _str(row["uri"]), _bool(row["ocr_processed"]), _str(row["created_date"]),
            _str(row["tags"]), _str(row["summary"]))


def parse_cdmap_row(row):
    return (_str(row["doc_id"]), _str(row["component_id"]), _str(row["relation_type"]))


LOAD_PLAN = [
    ("sensor_readings.csv", "sensor_readings",
     "INSERT INTO sensor_readings VALUES (?,?,?,?,?,?)", parse_sensor_row),
    ("quality_events.csv", "quality_events",
     "INSERT INTO quality_events VALUES (?,?,?,?,?,?,?)", parse_event_row),
    ("quality_predictions.csv", "quality_predictions",
     "INSERT INTO quality_predictions VALUES (?,?,?,?,?,?,?)", parse_prediction_row),
    ("module_eol_test.csv", "module_eol_test",
     "INSERT INTO module_eol_test VALUES (?,?,?,?,?,?,?,?,?,?)", parse_eol_row),
    ("unified_part_metadata.csv", "unified_part_metadata",
     "INSERT INTO unified_part_metadata VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", parse_part_row),
    ("document_metadata.csv", "document_metadata",
     "INSERT INTO document_metadata VALUES (?,?,?,?,?,?,?,?)", parse_doc_row),
    ("component_doc_map.csv", "component_doc_map",
     "INSERT INTO component_doc_map VALUES (?,?,?)", parse_cdmap_row),
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

    print("\nPACK-07 thermal crisis — HIGH risk predictions:")
    cursor.execute("""
        SELECT machine_id, prediction_time, defect_rate, risk_level, confidence
        FROM quality_predictions
        WHERE machine_id = 'PACK-07' AND risk_level = 'HIGH'
        ORDER BY prediction_time LIMIT 5
    """)
    for r in cursor.fetchall():
        print(f"  {r[0]}  {r[1]}  defect_rate={r[2]}  risk={r[3]}  conf={r[4]}")

    print("\nLOT-2026-0619 batch anomaly rate (module EOL test):")
    cursor.execute("""
        SELECT cell_lot,
               COUNT(DISTINCT module_id) AS total_modules,
               COUNT(DISTINCT CASE WHEN is_anomaly = 1 THEN module_id END) AS anomaly_modules,
               ROUND(COUNT(DISTINCT CASE WHEN is_anomaly = 1 THEN module_id END) * 100.0
                     / COUNT(DISTINCT module_id), 1) AS anomaly_rate
        FROM module_eol_test_v
        WHERE test_date = '2026-06-24'
        GROUP BY cell_lot
        ORDER BY anomaly_rate DESC
    """)
    for r in cursor.fetchall():
        print(f"  {r[0]:<16} total={r[1]:>3}  anomaly={r[2]:>2}  rate={r[3]}%")

    print("\nPACK-07 temperature peak (13:15–13:25):")
    cursor.execute("""
        SELECT event_time, value FROM sensor_readings
        WHERE machine_id = 'PACK-07' AND metric = 'temperature'
          AND event_time BETWEEN '2026-06-24 13:15:00' AND '2026-06-24 13:25:00'
        ORDER BY event_time
    """)
    for r in cursor.fetchall():
        print(f"  {r[0]}  temp={r[1]}")


def main():
    args = parse_args()
    print("=" * 70)
    print("Story01 Battery Pack — Load CSV Data into Impala")
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
    p = argparse.ArgumentParser(description="Load Story01 demo CSVs into iot_car_battery_db")
    p.add_argument("--host", default=IMPALA_HOST)
    p.add_argument("--port", type=int, default=IMPALA_PORT)
    p.add_argument("--user", default=USERNAME)
    p.add_argument("--password", default=PASSWORD)
    return p.parse_args()


if __name__ == "__main__":
    main()
