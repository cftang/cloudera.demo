#!/usr/bin/env python3
"""
Generate synthetic CSV demo data for UC1 — Predictive Maintenance (CNC Machining).

Time window : 2025-06-24 08:00–16:00 UTC (8 hours)
Machines    : M01 (tool wear), M02 (spindle bearing CRITICAL), M03 (edge anomaly)

Demo workflow inputs:
    machine_id=M02, alert_timestamp=2025-06-24T14:30:00, health_score=38.5

Usage:
    python generate_demo_data_uc1.py
"""

import csv
import json
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)
DATA_DIR = Path(__file__).parent

START = datetime(2025, 6, 24, 8, 0, 0)
END = datetime(2025, 6, 24, 16, 0, 0)
MACHINES = ["M01", "M02", "M03"]
AXES = ["x", "y", "z"]
WINDOW_MINUTES = 5


def minutes_elapsed(ts: datetime) -> float:
    return (ts - START).total_seconds() / 60.0


def baseline_rms(machine_id: str, axis: str, ts: datetime) -> float:
    """Return baseline vibration RMS with per-machine/axis offsets and noise."""
    base = {"M01": 0.95, "M02": 1.05, "M03": 0.90}[machine_id]
    axis_off = {"x": 0.0, "y": 0.05, "z": 0.10}[axis]
    noise = random.gauss(0, 0.04)
    return max(0.3, base + axis_off + noise)


def apply_scenario(machine_id: str, axis: str, ts: datetime, rms: float) -> float:
    mins = minutes_elapsed(ts)

    # M01 — gradual tool wear: Z-axis slowly rises over 8h
    if machine_id == "M01" and axis == "z":
        rms += (mins / 480.0) * 0.6

    # M02 — spindle bearing: Z-axis spike from 14:00 onward (360 min from start)
    if machine_id == "M02" and axis == "z" and mins >= 360:
        spike_progress = min(1.0, (mins - 360) / 30.0)
        rms += spike_progress * 2.8

    # M03 — edge anomaly burst around 11:45 (225 min from start)
    if machine_id == "M03" and 220 <= mins <= 235:
        rms += 1.2 if axis == "x" else 0.5

    return round(rms, 4)


def generate_vibration_readings():
    rows = []
    ts = START
    while ts < END:
        for machine_id in MACHINES:
            for axis in AXES:
                rms = baseline_rms(machine_id, axis, ts)
                rms = apply_scenario(machine_id, axis, ts, rms)
                peak = round(rms * random.uniform(1.3, 1.8), 4)
                rows.append({
                    "event_time": ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "machine_id": machine_id,
                    "axis": axis,
                    "vibration_rms": rms,
                    "vibration_peak": peak,
                    "unit": "mm/s",
                })
        ts += timedelta(minutes=1)
    return rows


def compute_health_for_window(machine_id: str, window_end: datetime, vib_rows: list) -> dict:
    """Aggregate vibration rows in the 5-min window ending at window_end."""
    window_start = window_end - timedelta(minutes=WINDOW_MINUTES)
    window_rows = [
        r for r in vib_rows
        if r["machine_id"] == machine_id
        and window_start <= datetime.strptime(r["event_time"], "%Y-%m-%d %H:%M:%S") <= window_end
    ]
    if not window_rows:
        return None

    def avg_axis(ax):
        vals = [r["vibration_rms"] for r in window_rows if r["axis"] == ax]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    rms_x, rms_y, rms_z = avg_axis("x"), avg_axis("y"), avg_axis("z")
    max_peak = max(r["vibration_peak"] for r in window_rows)
    std_vals = [r["vibration_rms"] for r in window_rows]
    mean_v = sum(std_vals) / len(std_vals)
    std_v = math.sqrt(sum((v - mean_v) ** 2 for v in std_vals) / len(std_vals)) if len(std_vals) > 1 else 0

    # Health score: 100 at baseline, drops with elevated vibration
    avg_rms = (rms_x + rms_y + rms_z) / 3.0
    health = max(10.0, min(100.0, 100.0 - (avg_rms - 0.9) * 35.0))
    anomaly = round(min(1.0, std_v * 0.8 + max(0, avg_rms - 1.5) * 0.3), 4)

    mins = minutes_elapsed(window_end)

    # M01 — gradual decline 85 → 58
    if machine_id == "M01":
        health = max(55.0, 85.0 - (mins / 480.0) * 27.0)

    # M02 — critical drop: threshold 387 so health=38.5 at 14:30 (mins=390), floor 30
    if machine_id == "M02" and mins >= 387:
        health = max(30.0, 40.0 - (mins - 387) * 0.5)

    # M03 — edge flag at 11:45 window
    edge_flag = machine_id == "M03" and 220 <= mins <= 230
    if edge_flag:
        anomaly = max(anomaly, 0.85)
        health = min(health, 52.0)

    return {
        "event_time": window_end.strftime("%Y-%m-%d %H:%M:%S"),
        "machine_id": machine_id,
        "health_score": round(health, 2),
        "anomaly_score": anomaly,
        "edge_alert_flag": "true" if edge_flag else "false",
        "vibration_rms_x": rms_x,
        "vibration_rms_y": rms_y,
        "vibration_rms_z": rms_z,
        "window_minutes": WINDOW_MINUTES,
    }


def generate_machine_health(vib_rows):
    rows = []
    window_end = START + timedelta(minutes=WINDOW_MINUTES)
    while window_end <= END:
        for machine_id in MACHINES:
            row = compute_health_for_window(machine_id, window_end, vib_rows)
            if row:
                rows.append(row)
        window_end += timedelta(minutes=WINDOW_MINUTES)
    return rows


def _health_lookup(health_rows, machine_id, pred_time):
    """Return the health row dict for a given machine + timestamp, or None."""
    for r in health_rows:
        if r["machine_id"] == machine_id and r["event_time"] == pred_time:
            return r
    return None


def generate_rul_predictions(health_rows):
    """Recent RUL predictions aligned to demo alert scenarios."""
    predictions = []

    # Alert rows: derive sensor values from the already-computed health table
    # so feature_window stays consistent with machine_health.csv.
    def _m02_alert_features(pred_time, fallback_z, fallback_h):
        row = _health_lookup(health_rows, "M02", pred_time)
        z = round(row["vibration_rms_z"], 2) if row else fallback_z
        h = round(row["health_score"], 1) if row else fallback_h
        return {"dominant_axis": "z", "vibration_rms_z": z, "health_score": h}

    alert_windows = [
        ("M02", "2025-06-24 14:30:00", 6.5, 0.91, "CRITICAL",
         _m02_alert_features("2025-06-24 14:30:00", 3.69, 38.5)),
        ("M02", "2025-06-24 14:25:00", 8.2, 0.88, "CRITICAL",
         _m02_alert_features("2025-06-24 14:25:00", 2.85, 42.0)),
        ("M03", "2025-06-24 11:45:00", 18.0, 0.79, "HIGH",
         {"edge_alert_flag": True, "anomaly_score": 0.87, "health_score": 51.0}),
        ("M01", "2025-06-24 15:55:00", 42.0, 0.82, "MEDIUM",
         {"dominant_axis": "z", "trend": "gradual_wear", "health_score": 58.0}),
        ("M01", "2025-06-24 12:00:00", 68.0, 0.85, "LOW",
         {"dominant_axis": "z", "trend": "gradual_wear", "health_score": 72.0}),
    ]
    for machine_id, pred_time, rul, conf, risk, features in alert_windows:
        predictions.append({
            "prediction_time": pred_time,
            "machine_id": machine_id,
            "rul_hours": rul,
            "confidence": conf,
            "risk_level": risk,
            "feature_window": json.dumps(features, separators=(",", ":")),
        })

    # Fill with routine low-risk predictions for fleet context
    for machine_id in MACHINES:
        for hour in [9, 10, 11, 13, 14]:
            if machine_id == "M02" and hour >= 14:
                continue
            predictions.append({
                "prediction_time": f"2025-06-24 {hour:02d}:00:00",
                "machine_id": machine_id,
                "rul_hours": round(random.uniform(80, 200), 1),
                "confidence": round(random.uniform(0.75, 0.92), 2),
                "risk_level": "LOW",
                "feature_window": json.dumps(
                    {"health_score": round(random.uniform(75, 95), 1)}, separators=(",", ":")
                ),
            })

    predictions.sort(key=lambda r: (r["prediction_time"], r["machine_id"]))
    return predictions


def write_csv(filename, rows, fieldnames):
    path = DATA_DIR / filename
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Wrote {len(rows):>5} rows → {path.name}")


def main():
    print("=" * 60)
    print("UC1 — Generate Demo CSV Data")
    print("=" * 60)

    vib = generate_vibration_readings()
    health = generate_machine_health(vib)
    rul = generate_rul_predictions(health)

    write_csv("vibration_readings.csv", vib,
              ["event_time", "machine_id", "axis", "vibration_rms", "vibration_peak", "unit"])
    write_csv("machine_health.csv", health,
              ["event_time", "machine_id", "health_score", "anomaly_score", "edge_alert_flag",
               "vibration_rms_x", "vibration_rms_y", "vibration_rms_z", "window_minutes"])
    write_csv("rul_predictions.csv", rul,
              ["prediction_time", "machine_id", "rul_hours", "confidence", "risk_level", "feature_window"])

    print("\nDemo alert row (M02):")
    m02_alert = next(r for r in health if r["machine_id"] == "M02" and r["event_time"] == "2025-06-24 14:30:00")
    print(f"  health_score={m02_alert['health_score']}  z_rms={m02_alert['vibration_rms_z']}")
    print("\n✓ Done")


if __name__ == "__main__":
    main()
