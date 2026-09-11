#!/usr/bin/env python3
"""
Generate synthetic CSV demo data for UC2 — Predictive Quality Management (Bike Manufacturing).

Time window : 2025-06-24 06:00–18:00 UTC (12 hours, production shift)
Machines    : CNC-01 (cnc), PAINT-01 (paint_booth), BAT-01 (battery_assembly)

Embedded scenarios:
  - Frame Welding Crisis (HIGH)  — CNC-01 vibration + temp spike ~10:15
  - Paint Booth Pattern (MEDIUM) — PAINT-01 humidity trending 13:00–15:00
  - Battery Anomaly (INVESTIGATE) — BAT-01 temperature pattern change ~09:30

Usage:
    python generate_demo_data_uc2.py
"""

import csv
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)
DATA_DIR = Path(__file__).parent

START = datetime(2025, 6, 24, 6, 0, 0)
END = datetime(2025, 6, 24, 18, 0, 0)
SAMPLE_INTERVAL_MIN = 5

MACHINES = {
    "CNC-01": {
        "process_type": "cnc",
        "metrics": {
            "vibration_rms": ("mm/s", 0.9, 0.08),
            "temperature": ("celsius", 42.0, 1.5),
            "sound_db": ("dB", 78.0, 2.0),
        },
    },
    "PAINT-01": {
        "process_type": "paint_booth",
        "metrics": {
            "humidity": ("percent", 45.0, 2.0),
            "pressure": ("kPa", 101.3, 0.5),
            "temperature": ("celsius", 22.0, 0.8),
        },
    },
    "BAT-01": {
        "process_type": "battery_assembly",
        "metrics": {
            "temperature": ("celsius", 28.0, 0.6),
            "voltage": ("volts", 3.7, 0.02),
        },
    },
}

WORK_ORDERS = [f"WO-2025-{600 + i:04d}" for i in range(1, 21)]
OPERATORS = ["OP-101", "OP-102", "OP-103", "OP-104", "OP-105"]

# Restrict random noise defect codes to the machine that can plausibly produce them.
# Prevents cross-machine codes (e.g. WELD-001 on PAINT-01) from confusing demo agents.
MACHINE_DEFECT_CODES = {
    "CNC-01":  ["WELD-001", "DIM-004"],
    "PAINT-01": ["PAINT-002", "DIM-004"],
    "BAT-01":  ["BAT-TEMP-003", "DIM-004"],
}


def minutes_elapsed(ts: datetime) -> float:
    return (ts - START).total_seconds() / 60.0


def metric_value(machine_id: str, metric: str, ts: datetime) -> float:
    cfg = MACHINES[machine_id]["metrics"][metric]
    unit, base, noise = cfg[0], cfg[1], cfg[2]
    val = base + random.gauss(0, noise)
    mins = minutes_elapsed(ts)

    # CNC-01 Frame Welding Crisis — spike ~10:15 (255 min from start)
    if machine_id == "CNC-01":
        if metric == "vibration_rms" and 250 <= mins <= 265:
            val += (mins - 250) * 0.15
        if metric == "temperature" and 250 <= mins <= 265:
            val += (mins - 250) * 0.4

    # PAINT-01 humidity trending up afternoon shift 13:00–15:00 (420–540 min)
    if machine_id == "PAINT-01" and metric == "humidity" and mins >= 420:
        val += min(18.0, (mins - 420) * 0.12)

    # BAT-01 temperature pattern change ~09:30 (210 min)
    if machine_id == "BAT-01" and metric == "temperature" and 205 <= mins <= 225:
        val += 3.5 * (1 - abs(mins - 210) / 10.0)

    return round(val, 4)


def generate_sensor_readings():
    rows = []
    ts = START
    while ts < END:
        for machine_id, cfg in MACHINES.items():
            for metric, (unit, _, _) in cfg["metrics"].items():
                rows.append({
                    "event_time": ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "machine_id": machine_id,
                    "process_type": cfg["process_type"],
                    "metric": metric,
                    "value": metric_value(machine_id, metric, ts),
                    "unit": unit,
                })
        ts += timedelta(minutes=SAMPLE_INTERVAL_MIN)
    return rows


def generate_quality_events():
    rows = []

    # +20 min offset: avoids cold-start noise in the first shift window (intentional)
    ts = START + timedelta(minutes=20)
    wo_idx = 0
    while ts < END:
        machine_id = list(MACHINES.keys())[wo_idx % len(MACHINES)]
        wo = WORK_ORDERS[wo_idx % len(WORK_ORDERS)]
        mins = minutes_elapsed(ts)

        if 250 <= mins <= 270 and machine_id == "CNC-01":
            event_type = "defect_logged"
            defect_code = "WELD-001"
        elif 420 <= mins <= 540 and machine_id == "PAINT-01":
            event_type = "quality_check"
            defect_code = ""
        elif 205 <= mins <= 230 and machine_id == "BAT-01":
            event_type = "quality_check"
            defect_code = ""
        elif random.random() < 0.08:
            event_type = random.choice(["defect_logged", "rework", "scrap"])
            defect_code = random.choice(MACHINE_DEFECT_CODES[machine_id])
        else:
            event_type = "quality_check"
            defect_code = ""

        payload = {
            "machine_id": machine_id,
            "process_type": MACHINES[machine_id]["process_type"],
            "event_type": event_type,
            "shift": "morning" if mins < 360 else "afternoon",
        }
        rows.append({
            "event_time": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "machine_id": machine_id,
            "work_order_id": wo,
            "event_type": event_type,
            "defect_code": defect_code,
            "operator_id": random.choice(OPERATORS),
            "raw_payload": json.dumps(payload, separators=(",", ":")),
        })
        wo_idx += 1
        ts += timedelta(minutes=9)

    return rows


def generate_quality_predictions(sensor_rows, event_rows):
    rows = []
    # +10 min offset: first prediction after one full 5-min sensor window (intentional)
    ts = START + timedelta(minutes=10)
    wo_idx = 0

    while ts < END:
        for machine_id in MACHINES:
            wo = WORK_ORDERS[wo_idx % len(WORK_ORDERS)]
            mins = minutes_elapsed(ts)

            defect_rate = round(random.uniform(0.01, 0.05), 4)
            risk = "LOW"
            confidence = round(random.uniform(0.78, 0.92), 2)
            features = {"machine_id": machine_id, "window_minutes": 5}

            # Frame Welding Crisis
            if machine_id == "CNC-01" and 250 <= mins <= 270:
                defect_rate = round(random.uniform(0.16, 0.24), 4)
                risk = "HIGH"
                confidence = round(random.uniform(0.85, 0.93), 2)
                features = {
                    "vibration_rms": 2.1, "temperature": 52.3,
                    "trigger": "frame_welding_crisis",
                }

            # Paint Booth Pattern
            elif machine_id == "PAINT-01" and 420 <= mins <= 540:
                defect_rate = round(random.uniform(0.08, 0.12), 4)
                risk = "MEDIUM"
                confidence = round(random.uniform(0.80, 0.88), 2)
                features = {
                    "humidity": 58.0 + (mins - 420) * 0.05,
                    "shift": "afternoon",
                    "trigger": "paint_booth_humidity",
                }

            # Battery Anomaly
            elif machine_id == "BAT-01" and 205 <= mins <= 235:
                defect_rate = round(random.uniform(0.10, 0.14), 4)
                risk = "INVESTIGATE"
                confidence = round(random.uniform(0.72, 0.82), 2)
                features = {
                    "temperature_delta": 3.2,
                    "anomaly_score": -0.3,
                    "trigger": "battery_temp_pattern",
                }

            rows.append({
                "prediction_time": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "machine_id": machine_id,
                "work_order_id": wo,
                "defect_rate": defect_rate,
                "risk_level": risk,
                "confidence": confidence,
                "feature_window": json.dumps(features, separators=(",", ":")),
            })
            wo_idx += 1
        ts += timedelta(minutes=SAMPLE_INTERVAL_MIN)

    return rows


def write_csv(filename, rows, fieldnames):
    path = DATA_DIR / filename
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Wrote {len(rows):>5} rows → {path.name}")


def main():
    print("=" * 60)
    print("UC2 — Generate Demo CSV Data")
    print("=" * 60)

    sensors = generate_sensor_readings()
    events = generate_quality_events()
    preds = generate_quality_predictions(sensors, events)

    write_csv("sensor_readings.csv", sensors,
              ["event_time", "machine_id", "process_type", "metric", "value", "unit"])
    write_csv("quality_events.csv", events,
              ["event_time", "machine_id", "work_order_id", "event_type",
               "defect_code", "operator_id", "raw_payload"])
    write_csv("quality_predictions.csv", preds,
              ["prediction_time", "machine_id", "work_order_id", "defect_rate",
               "risk_level", "confidence", "feature_window"])

    high = [p for p in preds if p["risk_level"] == "HIGH"]
    print(f"\nHIGH-risk predictions: {len(high)} (Frame Welding Crisis windows)")
    print("✓ Done")


if __name__ == "__main__":
    main()
