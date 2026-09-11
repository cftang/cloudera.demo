#!/usr/bin/env python3
"""
Generate synthetic CSV demo data for Story 01 — New-Energy Battery Pack Assembly Line
(热失控前的 90 分钟 / 装车前拦住一批异常电芯).

One dataset, two narratives. This single seed serves BOTH:
  - the full 5-Agent time-series story (01_battery_pack.md / 01_battery_lab.md)
    → sensor_readings + quality_events + quality_predictions
  - the refined 3-Agent EOL story (新能源电池包装配线故事_精简版.pdf)
    → module_eol_test (per-module End-of-Line test rows)

Shared anchors (identical numbers in both docs):
  machine  = PACK-07          cell_lot = LOT-2026-0619
  spike    = +3.9°C @ 13:20   voltage_std 0.006 → 0.021   confidence 0.88
  batch    = 44 modules, 7 anomalies → 15.9% anomaly rate  (others ≈ 1.1%)
  work_order = WO-2026-0624   severity = HIGH

Time window : 2026-06-24 06:00–18:00 (12-hour production shift)
Machines    : PACK-07 (anchor HIGH), PACK-02 / PACK-05 (peers on LOT-2026-0619),
              PACK-03 (press-force drift, MEDIUM), PACK-11 (voltage intermittent, INVESTIGATE)

Usage:
    python generate_demo_data_battery.py
"""

import csv
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)
DATA_DIR = Path(__file__).parent

START = datetime(2026, 6, 24, 6, 0, 0)
END = datetime(2026, 6, 24, 18, 0, 0)
SAMPLE_INTERVAL_MIN = 5
TEST_DATE = "2026-06-24"

PROCESS = "module_assembly"

# metric -> (unit, baseline mean, gauss sigma). Baseline mu/sigma for temperature
# match the 30-day figures cited in the story (mu≈28.2, sigma≈0.55).
METRICS = {
    "temperature": ("celsius", 28.2, 0.55),
    "voltage_std": ("volts", 0.006, 0.0008),
    "press_force": ("kN", 3.02, 0.05),
}

MACHINES = ["PACK-07", "PACK-02", "PACK-05", "PACK-03", "PACK-11"]

# The culprit incoming cell lot + the healthy comparison lots.
CULPRIT_LOT = "LOT-2026-0619"
OTHER_LOTS = ["LOT-2026-0611", "LOT-2026-0613", "LOT-2026-0615", "LOT-2026-0617"]

# Machines that consumed the culprit lot today (drives both the machine-axis peer
# comparison in the .md and the batch-axis anomaly-rate query in the PDF).
LOT0619_MACHINES = ["PACK-07", "PACK-02", "PACK-05"]

# Midday plateau (12:00–14:20) when LOT-2026-0619 was being assembled — a mild
# per-machine temperature offset so the batch cross-comparison ranks PACK-07 > 02 > 05.
LOT0619_PLATEAU_MIN = (360, 500)
LOT0619_TEMP_OFFSET = {"PACK-07": 1.6, "PACK-02": 0.9, "PACK-05": 0.7}

WORK_ORDERS = [f"WO-2026-{620 + i:04d}" for i in range(1, 21)]
OPERATORS = ["OP-201", "OP-202", "OP-203", "OP-204", "OP-205"]

MACHINE_DEFECT_CODES = {
    "PACK-07": ["THM-042", "DCR-019"],
    "PACK-02": ["DCR-019", "DIM-004"],
    "PACK-05": ["DCR-019", "DIM-004"],
    "PACK-03": ["PRESS-004", "DIM-004"],
    "PACK-11": ["VOLT-007", "DIM-004"],
}


def minutes_elapsed(ts: datetime) -> float:
    return (ts - START).total_seconds() / 60.0


# --------------------------------------------------------------------------- #
# 1. sensor_readings — narrow time series
# --------------------------------------------------------------------------- #
def metric_value(machine_id: str, metric: str, ts: datetime) -> float:
    unit, base, noise = METRICS[metric]
    val = base + random.gauss(0, noise)
    mins = minutes_elapsed(ts)
    lo, hi = LOT0619_PLATEAU_MIN

    if metric == "temperature":
        # LOT-2026-0619 midday plateau on the three consuming machines.
        if machine_id in LOT0619_TEMP_OFFSET and lo <= mins <= hi:
            val += LOT0619_TEMP_OFFSET[machine_id]
        # PACK-07 thermal spike: triangular peak +2.2 on top of the +1.6 plateau
        # at 13:20 (440 min) → 28.2 + 3.8 ≈ 32.2 (delta ≈3.9 vs baseline).
        if machine_id == "PACK-07" and 430 <= mins <= 450:
            val += 2.2 * (1 - abs(mins - 440) / 10.0)
        # Peer packs on the same lot show smaller localized bumps (max ≈ 31.0 / 30.6),
        # so the batch cross-comparison reads "broadly elevated" across the lot.
        if machine_id == "PACK-02" and 390 <= mins <= 410:
            val += 1.9 * (1 - abs(mins - 400) / 10.0)
        if machine_id == "PACK-05" and 410 <= mins <= 430:
            val += 1.7 * (1 - abs(mins - 420) / 10.0)

    if metric == "voltage_std":
        # PACK-07 dispersion climbs 0.006 → 0.021 across the spike window.
        if machine_id == "PACK-07" and 430 <= mins <= 450:
            val += 0.016 * (1 - abs(mins - 440) / 10.0)
        # PACK-11 intermittent single-module deviation around 09:30 (peak 210 min),
        # sustained across a wider window so the INVESTIGATE class is learnable.
        if machine_id == "PACK-11" and 180 <= mins <= 260:
            val += 0.009 + 0.004 * (1 - abs(mins - 210) / 30.0)

    if metric == "press_force":
        # PACK-03 press-force drift: elevated plateau 13:00–15:00 (peaking ~14:10),
        # then corrected back to baseline. The window matches the MEDIUM label window
        # exactly, so no LOW rows carry a high press_force (clean class separation).
        if machine_id == "PACK-03" and 400 <= mins <= 560:
            val += min(1.10, 0.70 + (mins - 400) * 0.004)

    return round(val, 4)


def generate_sensor_readings():
    rows = []
    ts = START
    while ts < END:
        for machine_id in MACHINES:
            for metric in METRICS:
                unit = METRICS[metric][0]
                rows.append({
                    "event_time": ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "machine_id": machine_id,
                    "process_type": PROCESS,
                    "metric": metric,
                    "value": metric_value(machine_id, metric, ts),
                    "unit": unit,
                })
        ts += timedelta(minutes=SAMPLE_INTERVAL_MIN)
    return rows


# --------------------------------------------------------------------------- #
# 2. quality_events — work-order level; raw_payload carries cell_lot + module_id
# --------------------------------------------------------------------------- #
def generate_quality_events():
    rows = []
    ts = START + timedelta(minutes=20)
    wo_idx = 0
    mod_seq = 0
    while ts < END:
        machine_id = MACHINES[wo_idx % len(MACHINES)]
        wo = WORK_ORDERS[wo_idx % len(WORK_ORDERS)]
        mins = minutes_elapsed(ts)
        lo, hi = LOT0619_PLATEAU_MIN

        # Machines on the culprit lot get cell_lot=LOT-2026-0619 during the plateau;
        # everyone else draws from the healthy lots. This makes the .md batch join
        # (JOIN quality_events ON cell_lot='LOT-2026-0619') return PACK-07/02/05.
        if machine_id in LOT0619_MACHINES and lo <= mins <= hi:
            cell_lot = CULPRIT_LOT
        else:
            cell_lot = random.choice(OTHER_LOTS)

        if machine_id == "PACK-07" and 430 <= mins <= 450:
            event_type, defect_code = "defect_logged", "THM-042"
        elif machine_id == "PACK-03" and 480 <= mins <= 505:
            event_type, defect_code = "quality_check", ""
        elif machine_id == "PACK-11" and 200 <= mins <= 225:
            event_type, defect_code = "quality_check", ""
        elif random.random() < 0.08:
            event_type = random.choice(["defect_logged", "rework", "scrap"])
            defect_code = random.choice(MACHINE_DEFECT_CODES[machine_id])
        else:
            event_type, defect_code = "quality_check", ""

        mod_seq += 1
        payload = {
            "machine_id": machine_id,
            "process_type": PROCESS,
            "event_type": event_type,
            "cell_lot": cell_lot,
            "module_id": f"MOD-2026-0624-{mod_seq:04d}",
            "shift": "morning" if mins < 360 else "afternoon",
        }
        rows.append({
            "event_time": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "machine_id": machine_id,
            "work_order_id": wo,
            "event_type": event_type,
            "defect_code": defect_code,
            "operator_id": random.choice(OPERATORS),
            "raw_payload": json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        })
        wo_idx += 1
        ts += timedelta(minutes=9)

    # Curated anchor events: guarantee a LOT-2026-0619 quality_event sits within
    # ±5 min of each peer pack's temperature peak, so the .md batch cross-comparison
    # join surfaces the documented per-machine maxes (PACK-07 32.2 / 02 31.0 / 05 30.6).
    anchors = [
        ("PACK-07", "2026-06-24 13:20:00", "defect_logged", "THM-042", mod_seq + 1),
        ("PACK-02", "2026-06-24 12:40:00", "quality_check", "", mod_seq + 2),
        ("PACK-05", "2026-06-24 13:00:00", "quality_check", "", mod_seq + 3),
    ]
    for machine_id, when, event_type, defect_code, seq in anchors:
        payload = {
            "machine_id": machine_id, "process_type": PROCESS, "event_type": event_type,
            "cell_lot": CULPRIT_LOT, "module_id": f"MOD-2026-0624-{seq:04d}", "shift": "afternoon",
        }
        rows.append({
            "event_time": when, "machine_id": machine_id,
            "work_order_id": WORK_ORDERS[0], "event_type": event_type,
            "defect_code": defect_code, "operator_id": OPERATORS[0],
            "raw_payload": json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        })
    return rows


# --------------------------------------------------------------------------- #
# 3. quality_predictions — 5-min/machine model output
# --------------------------------------------------------------------------- #
def generate_quality_predictions():
    rows = []
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

            # PACK-07 module thermal / electrical-consistency crisis → HIGH.
            if machine_id == "PACK-07" and 430 <= mins <= 450:
                is_anchor = ts == datetime(2026, 6, 24, 13, 20, 0)
                defect_rate = 0.19 if is_anchor else round(random.uniform(0.16, 0.24), 4)
                risk = "HIGH"
                confidence = 0.88 if is_anchor else round(random.uniform(0.85, 0.92), 2)
                features = {
                    "temperature_delta": 3.9,
                    "voltage_std": 0.021,
                    "press_force": 3.05,
                    "dcr": 0.86,
                    "cell_lot": CULPRIT_LOT,
                    "anomaly_score": -0.34,
                    "trigger": "module_electrical_consistency_anomaly",
                }
            # PACK-03 press-force drift → MEDIUM (sustained afternoon window).
            elif machine_id == "PACK-03" and 400 <= mins <= 560:
                defect_rate = round(random.uniform(0.08, 0.12), 4)
                risk = "MEDIUM"
                confidence = round(random.uniform(0.80, 0.88), 2)
                features = {
                    "press_force": round(3.72 + (mins - 400) * 0.004, 3),
                    "trigger": "press_force_drift",
                }
            # PACK-11 intermittent voltage dispersion → INVESTIGATE (wider window).
            elif machine_id == "PACK-11" and 180 <= mins <= 260:
                defect_rate = round(random.uniform(0.10, 0.14), 4)
                risk = "INVESTIGATE"
                confidence = round(random.uniform(0.72, 0.82), 2)
                features = {
                    "voltage_std": 0.015,
                    "anomaly_score": -0.28,
                    "trigger": "voltage_consistency_intermittent",
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


# --------------------------------------------------------------------------- #
# 4. module_eol_test — per-module End-of-Line test (PDF 3-Agent narrative)
# --------------------------------------------------------------------------- #
def _eol_row(seq, machine_id, cell_lot, is_anomaly):
    """Build one module EOL test row. Anomalies carry the thermal + dispersion +
    high-DCR signature; healthy modules cluster near the batch mean."""
    if is_anomaly:
        temp_delta = round(random.uniform(3.4, 4.2), 2)
        voltage_std = round(random.uniform(0.018, 0.024), 4)
        dcr = round(random.uniform(0.83, 0.88), 3)      # near / over 0.85 mΩ spec
        anomaly_type = "electrical_consistency"
    elif cell_lot == CULPRIT_LOT:
        # Healthy 0619 modules still sit slightly high (batch DCR mean ≈ 0.82 mΩ).
        temp_delta = round(random.uniform(-0.4, 1.3), 2)
        voltage_std = round(random.uniform(0.005, 0.008), 4)
        dcr = round(random.uniform(0.79, 0.835), 3)
        anomaly_type = ""
    else:
        temp_delta = round(random.uniform(-0.6, 0.9), 2)
        voltage_std = round(random.uniform(0.004, 0.007), 4)
        dcr = round(random.uniform(0.68, 0.80), 3)
        anomaly_type = ""
    return {
        "test_id": f"EOL-2026-0624-{seq:04d}",
        "module_id": f"MOD-2026-0624-{seq:04d}",
        "machine_id": machine_id,
        "cell_lot": cell_lot,
        "test_date": TEST_DATE,
        "temperature_delta": temp_delta,
        "voltage_std": voltage_std,
        "dcr": dcr,
        "is_anomaly": 1 if is_anomaly else 0,
        "anomaly_type": anomaly_type,
    }


def generate_module_eol_test():
    rows = []
    seq = 0

    # LOT-2026-0619 → 44 modules, 7 anomalies (15.9%), spread across PACK-07/02/05.
    lot0619_plan = [("PACK-07", 16, 4), ("PACK-02", 15, 2), ("PACK-05", 13, 1)]
    for machine_id, total, n_anom in lot0619_plan:
        flags = [True] * n_anom + [False] * (total - n_anom)
        random.shuffle(flags)
        for is_anom in flags:
            seq += 1
            rows.append(_eol_row(seq, machine_id, CULPRIT_LOT, is_anom))

    # Healthy comparison lots → 186 modules total, 2 anomalies (~1.1%).
    other_plan = [
        ("LOT-2026-0611", "PACK-02", 47, 1),
        ("LOT-2026-0613", "PACK-05", 47, 0),
        ("LOT-2026-0615", "PACK-03", 46, 1),
        ("LOT-2026-0617", "PACK-11", 46, 0),
    ]
    for cell_lot, machine_id, total, n_anom in other_plan:
        flags = [True] * n_anom + [False] * (total - n_anom)
        random.shuffle(flags)
        for is_anom in flags:
            seq += 1
            rows.append(_eol_row(seq, machine_id, cell_lot, is_anom))

    return rows


# --------------------------------------------------------------------------- #
# 5. unified_part_metadata — 3D part catalog (flat + JSON columns, loadable)
# --------------------------------------------------------------------------- #
def _part(part_number, object_name, part_type, source_type, tech_specs,
          bom_parent, bom_children, bom_level, ocr=False):
    return {
        "part_number": part_number,
        "object_name": object_name,
        "part_type": part_type,
        "version": "A.1",
        "status": "RELEASED",
        "source_type": source_type,
        "storage_url": f"ofs://ozone/pdm/{part_number}.{source_type.lower()}",
        "viewer_url": f"https://viewer.internal/3d/{part_number}",
        "created_date": "2026-05-10 09:00:00",
        "modified_date": "2026-06-01 14:30:00",
        "tech_specs": json.dumps(tech_specs, separators=(",", ":")),
        "bom_hierarchy": json.dumps(
            {"parent_assembly": bom_parent, "children": bom_children, "bom_level": bom_level},
            separators=(",", ":"),
        ),
        "data_lineage": json.dumps(
            {"source_system": "PLM", "ingested_by": "nifi_pdm_flow",
             "ingested_at": "2026-06-02 03:15:00", "ocr_processed": ocr},
            separators=(",", ":"),
        ),
    }


def generate_unified_part_metadata():
    rows = [
        _part(
            "PART-2026-BAT-MOD-07", "电池模组支架 Module Bracket", "COMPONENT", "CATIA",
            {"material_grade": "6061-T6", "surface_treatment": "anodized",
             "heat_dissipation_area_cm2": 182.4, "max_operating_temp_c": 60.0, "weight_kg": 1.84},
            "PART-2026-BAT-PACK-01", [], 3, ocr=False,
        ),
        _part(
            "PART-2026-BAT-PACK-01", "电池包总成 Pack Assembly", "ASSEMBLY", "STEP",
            {"material_grade": "steel-Q345", "surface_treatment": "e-coat",
             "heat_dissipation_area_cm2": 0.0, "max_operating_temp_c": 65.0, "weight_kg": 312.0},
            "", ["PART-2026-BAT-MOD-07", "PART-2026-BAT-CELL-HOLD", "PART-2026-BAT-BUSBAR"], 1,
        ),
        _part(
            "PART-2026-BAT-CELL-HOLD", "电芯支架 Cell Holder", "COMPONENT", "CATIA",
            {"material_grade": "PA66-GF30", "surface_treatment": "none",
             "heat_dissipation_area_cm2": 96.0, "max_operating_temp_c": 90.0, "weight_kg": 0.42},
            "PART-2026-BAT-PACK-01", [], 3,
        ),
        _part(
            "PART-2026-BAT-BUSBAR", "汇流排 Busbar", "COMPONENT", "STEP",
            {"material_grade": "copper-C11000", "surface_treatment": "tin-plated",
             "heat_dissipation_area_cm2": 40.0, "max_operating_temp_c": 105.0, "weight_kg": 0.31},
            "PART-2026-BAT-PACK-01", [], 3,
        ),
    ]
    # Filler released parts so the catalog reads like a real PDM extract.
    for i in range(1, 21):
        st = ["CATIA", "STEP", "PDF_DRAWING", "SCAN"][i % 4]
        rows.append(_part(
            f"PART-2026-BAT-GEN-{i:02d}", f"通用件 Generic Part {i:02d}",
            random.choice(["COMPONENT", "FASTENER", "BRACKET"]), st,
            {"material_grade": random.choice(["6061-T6", "steel-Q345", "PA66-GF30"]),
             "surface_treatment": "none", "heat_dissipation_area_cm2": round(random.uniform(10, 120), 1),
             "max_operating_temp_c": round(random.uniform(60, 110), 1),
             "weight_kg": round(random.uniform(0.05, 3.5), 2)},
            "PART-2026-BAT-PACK-01", [], 3, ocr=(st == "SCAN"),
        ))
    return rows


# --------------------------------------------------------------------------- #
# 6. document_metadata — SOP / COA / ECN knowledge sources
# --------------------------------------------------------------------------- #
def generate_document_metadata():
    rows = [
        {"doc_id": "SOP-THM-042", "title": "动力电池热管理异常处置指南 §4.2",
         "source_type": "PDF", "uri": "ofs://ozone/kb/SOP-THM-042.pdf", "ocr_processed": "false",
         "created_date": "2025-11-02 10:00:00",
         "tags": json.dumps(["thermal", "SOP", "disposition"]),
         "summary": "模组温升异常应立即隔离对应批次并复检在制模组。"},
        {"doc_id": "COA-0619", "title": "电芯来料合格证 (LOT-2026-0619)",
         "source_type": "PDF", "uri": "ofs://ozone/kb/COA-0619_scan.pdf", "ocr_processed": "true",
         "created_date": "2026-06-19 08:20:00",
         "tags": json.dumps(["COA", "incoming", "cell_lot", "OCR"]),
         "summary": "LOT-2026-0619 来料内阻(DCR)均值 0.82mΩ,接近规格上限 0.85mΩ。"},
        {"doc_id": "ECN-2026-0311", "title": "电芯供应商内阻偏高变更通知",
         "source_type": "MSG", "uri": "ofs://ozone/kb/ECN-2026-0311.msg", "ocr_processed": "false",
         "created_date": "2026-03-11 16:05:00",
         "tags": json.dumps(["ECN", "supplier", "DCR"]),
         "summary": "供应商预警部分批次电芯内阻偏高,建议加严来料复测。"},
        {"doc_id": "SOP-QUAL-028", "title": "动力电池质量异常处置 SOP §3.1",
         "source_type": "PDF", "uri": "ofs://ozone/kb/SOP-QUAL-028.pdf", "ocr_processed": "false",
         "created_date": "2025-09-15 09:30:00",
         "tags": json.dumps(["quality", "SOP", "batch"]),
         "summary": "同一电芯批次 EOL 一致性异常≥2 起或异常率>3% 时须暂停使用并隔离在制与库存。"},
        {"doc_id": "DRW-BAT-MOD-07", "title": "模组支架工程图 PART-2026-BAT-MOD-07",
         "source_type": "PDF", "uri": "ofs://ozone/kb/PART-2026-BAT-MOD-07_drawing.pdf",
         "ocr_processed": "false", "created_date": "2026-05-10 09:05:00",
         "tags": json.dumps(["drawing", "bracket", "3D"]),
         "summary": "模组支架工程图,材料 6061-T6,散热面积 182.4 cm²。"},
    ]
    for i in range(1, 26):
        st = ["PDF", "MSG", "CHECKLIST", "SCAN"][i % 4]
        rows.append({
            "doc_id": f"DOC-GEN-{i:03d}", "title": f"通用文档 Generic Doc {i:03d}",
            "source_type": st, "uri": f"ofs://ozone/kb/DOC-GEN-{i:03d}.{st.lower()}",
            "ocr_processed": "true" if st == "SCAN" else "false",
            "created_date": "2026-04-01 12:00:00",
            "tags": json.dumps(["generic"]),
            "summary": "常规质量/工艺参考文档。"},
        )
    return rows


# --------------------------------------------------------------------------- #
# 7. component_doc_map — component_id ↔ doc_id bridge
# --------------------------------------------------------------------------- #
def generate_component_doc_map():
    rows = [
        {"doc_id": "SOP-THM-042", "component_id": "PART-2026-BAT-MOD-07", "relation_type": "disposition_guide"},
        {"doc_id": "COA-0619", "component_id": "PART-2026-BAT-MOD-07", "relation_type": "incoming_coa"},
        {"doc_id": "ECN-2026-0311", "component_id": "PART-2026-BAT-MOD-07", "relation_type": "supplier_ecn"},
        {"doc_id": "SOP-QUAL-028", "component_id": "PART-2026-BAT-MOD-07", "relation_type": "quality_sop"},
        {"doc_id": "DRW-BAT-MOD-07", "component_id": "PART-2026-BAT-MOD-07", "relation_type": "engineering_drawing"},
        {"doc_id": "SOP-THM-042", "component_id": "PART-2026-BAT-PACK-01", "relation_type": "disposition_guide"},
        {"doc_id": "SOP-QUAL-028", "component_id": "PART-2026-BAT-CELL-HOLD", "relation_type": "quality_sop"},
    ]
    for i in range(1, 21):
        rows.append({
            "doc_id": f"DOC-GEN-{i:03d}",
            "component_id": f"PART-2026-BAT-GEN-{i:02d}" if i <= 20 else "PART-2026-BAT-PACK-01",
            "relation_type": "reference",
        })
    return rows


# --------------------------------------------------------------------------- #
def write_csv(filename, rows, fieldnames):
    path = DATA_DIR / filename
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Wrote {len(rows):>5} rows → {path.name}")


def main():
    print("=" * 64)
    print("Story 01 — Battery Pack Assembly: Generate Demo CSV Data")
    print("=" * 64)

    sensors = generate_sensor_readings()
    events = generate_quality_events()
    preds = generate_quality_predictions()
    eol = generate_module_eol_test()
    parts = generate_unified_part_metadata()
    docs = generate_document_metadata()
    cdmap = generate_component_doc_map()

    write_csv("sensor_readings.csv", sensors,
              ["event_time", "machine_id", "process_type", "metric", "value", "unit"])
    write_csv("quality_events.csv", events,
              ["event_time", "machine_id", "work_order_id", "event_type",
               "defect_code", "operator_id", "raw_payload"])
    write_csv("quality_predictions.csv", preds,
              ["prediction_time", "machine_id", "work_order_id", "defect_rate",
               "risk_level", "confidence", "feature_window"])
    write_csv("module_eol_test.csv", eol,
              ["test_id", "module_id", "machine_id", "cell_lot", "test_date",
               "temperature_delta", "voltage_std", "dcr", "is_anomaly", "anomaly_type"])
    write_csv("unified_part_metadata.csv", parts,
              ["part_number", "object_name", "part_type", "version", "status", "source_type",
               "storage_url", "viewer_url", "created_date", "modified_date",
               "tech_specs", "bom_hierarchy", "data_lineage"])
    write_csv("document_metadata.csv", docs,
              ["doc_id", "title", "source_type", "uri", "ocr_processed",
               "created_date", "tags", "summary"])
    write_csv("component_doc_map.csv", cdmap,
              ["doc_id", "component_id", "relation_type"])

    # --- anchor summary ---------------------------------------------------- #
    lot0619 = [r for r in eol if r["cell_lot"] == CULPRIT_LOT]
    lot0619_anom = sum(r["is_anomaly"] for r in lot0619)
    others = [r for r in eol if r["cell_lot"] != CULPRIT_LOT]
    others_anom = sum(r["is_anomaly"] for r in others)
    high = [p for p in preds if p["risk_level"] == "HIGH"]

    print("\nAnchor checks")
    print(f"  LOT-2026-0619 : {len(lot0619)} modules, {lot0619_anom} anomalies "
          f"→ {100 * lot0619_anom / len(lot0619):.1f}%")
    print(f"  other lots    : {len(others)} modules, {others_anom} anomalies "
          f"→ {100 * others_anom / len(others):.1f}%")
    print(f"  HIGH predictions (PACK-07): {len(high)}")
    print("✓ Done")


if __name__ == "__main__":
    main()
