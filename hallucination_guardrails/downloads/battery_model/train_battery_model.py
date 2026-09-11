#!/usr/bin/env python3
"""
Train the three Battery Pack QA models for Story 01.

Input  : ../battery_demo_data/sensor_readings.csv       (features, narrow format)
         ../battery_demo_data/quality_predictions.csv    (risk_level labels)
         ../battery_demo_data/quality_events.csv          (cell_lot per window)
Output : battery_anomaly_detector.pkl   (IsolationForest — thermal anomaly)
         battery_risk_classifier.pkl    (XGBoost — thermal-runaway risk class)
         battery_voltage_regressor.pkl  (Ridge — voltage-consistency drift)
         feature_list.json, risk_encoder.json, cell_lot_encoder.json

The prediction models are classic ML (scikit-learn / XGBoost), not generative AI —
the Agent orchestrates and reasons; the models predict.

Usage  : python train_battery_model.py
"""

import json
import math
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import Ridge
from sklearn.metrics import accuracy_score, mean_absolute_error, mean_squared_error
from sklearn.model_selection import train_test_split

DATA_DIR = Path(__file__).parent.parent / "battery_demo_data"
MODEL_DIR = Path(__file__).parent

RISK_ENCODER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "INVESTIGATE": 3}

# IsolationForest input (unsupervised thermal-anomaly detector).
ANOMALY_FEATURES = ["temperature", "temperature_delta", "press_force", "voltage_std"]
# XGBoost risk classifier input.
CLASSIFIER_FEATURES = ["temperature_delta", "voltage_std", "press_force", "cell_lot_enc", "anomaly_score"]
# Ridge voltage-consistency regressor input → predicts voltage_std.
VOLTAGE_FEATURES = ["temperature", "press_force", "cell_lot_enc"]


def _try_xgb():
    try:
        from xgboost import XGBClassifier
        return XGBClassifier
    except ImportError:
        from sklearn.ensemble import GradientBoostingClassifier
        print("  xgboost not found — falling back to sklearn GradientBoosting")
        return GradientBoostingClassifier


def _wide_sensors() -> pd.DataFrame:
    sensors = pd.read_csv(DATA_DIR / "sensor_readings.csv", parse_dates=["event_time"])
    wide = sensors.pivot_table(
        index=["event_time", "machine_id", "process_type"],
        columns="metric", values="value", aggfunc="mean",
    ).reset_index()
    wide.columns.name = None
    for col in ("temperature", "voltage_std", "press_force"):
        if col not in wide.columns:
            wide[col] = 0.0
    wide[["temperature", "voltage_std", "press_force"]] = \
        wide[["temperature", "voltage_std", "press_force"]].fillna(0.0)
    # temperature_delta vs per-machine baseline mean.
    baseline = wide.groupby("machine_id")["temperature"].transform("mean")
    wide["temperature_delta"] = (wide["temperature"] - baseline).round(4)
    return wide.sort_values("event_time").reset_index(drop=True)


def _cell_lot_per_window(wide: pd.DataFrame) -> pd.Series:
    """Attach the nearest quality_event cell_lot to each sensor window."""
    events = pd.read_csv(DATA_DIR / "quality_events.csv", parse_dates=["event_time"])
    events["cell_lot"] = events["raw_payload"].apply(
        lambda p: json.loads(p).get("cell_lot", "UNKNOWN")
    )
    events = events[["event_time", "machine_id", "cell_lot"]].sort_values("event_time")
    frames = []
    for m in wide["machine_id"].unique():
        w = wide[wide["machine_id"] == m][["event_time"]].copy()
        e = events[events["machine_id"] == m][["event_time", "cell_lot"]].copy()
        if e.empty:
            w["cell_lot"] = "UNKNOWN"
        else:
            w = pd.merge_asof(w, e, on="event_time", direction="nearest",
                              tolerance=pd.Timedelta("30min"))
        w["machine_id"] = m
        frames.append(w)
    merged = pd.concat(frames).sort_index()
    return merged["cell_lot"].fillna("UNKNOWN").reset_index(drop=True)


def _merge_labels(wide: pd.DataFrame) -> pd.DataFrame:
    preds = pd.read_csv(DATA_DIR / "quality_predictions.csv", parse_dates=["prediction_time"])
    preds = preds.sort_values("prediction_time").reset_index(drop=True)
    frames = []
    for m in wide["machine_id"].unique():
        w = wide[wide["machine_id"] == m].copy()
        p = preds[preds["machine_id"] == m][
            ["prediction_time", "defect_rate", "risk_level"]
        ].rename(columns={"prediction_time": "event_time"})
        merged = pd.merge_asof(w, p, on="event_time",
                               tolerance=pd.Timedelta("5min"), direction="nearest")
        frames.append(merged)
    df = pd.concat(frames, ignore_index=True)
    return df.dropna(subset=["risk_level"]).reset_index(drop=True)


def main() -> None:
    print("=" * 60)
    print("Story01 Battery Pack — Train QA Models")
    print("=" * 60)

    wide = _wide_sensors()
    wide["cell_lot"] = _cell_lot_per_window(wide)
    df = _merge_labels(wide)
    print(f"  Merged rows: {len(df)}")

    # Encode cell_lot to a stable int (saved for inference; unseen → 0).
    lots = sorted(df["cell_lot"].unique())
    cell_lot_encoder = {lot: i for i, lot in enumerate(lots)}
    df["cell_lot_enc"] = df["cell_lot"].map(cell_lot_encoder).astype(int)

    # 1) IsolationForest — thermal anomaly detector (unsupervised).
    # Fit on plain arrays (no feature names) so numpy-array inference is warning-free.
    iso = IsolationForest(n_estimators=150, contamination=0.08, random_state=42)
    iso.fit(df[ANOMALY_FEATURES].astype(float).values)
    df["anomaly_score"] = iso.decision_function(df[ANOMALY_FEATURES].astype(float).values).round(4)
    print(f"  IsolationForest trained on {len(df)} rows "
          f"(anomaly_score range {df['anomaly_score'].min():.3f}..{df['anomaly_score'].max():.3f})")

    # 2) XGBoost — thermal-runaway risk classifier.
    XGBClassifier = _try_xgb()
    X_clf = df[CLASSIFIER_FEATURES].astype(float).values
    y_clf = df["risk_level"].map(RISK_ENCODER).astype(int)
    Xtr, Xte, ytr, yte = train_test_split(X_clf, y_clf, test_size=0.2, random_state=42,
                                          stratify=y_clf if y_clf.nunique() > 1 else None)
    clf_kwargs = {"n_estimators": 250, "max_depth": 5, "random_state": 42}
    try:
        clf = XGBClassifier(**clf_kwargs, eval_metric="mlogloss", use_label_encoder=False)
    except TypeError:
        clf = XGBClassifier(**clf_kwargs)
    # Balanced sample weights — the LOW class dominates; upweight the rare
    # HIGH / MEDIUM / INVESTIGATE scenarios so they stay learnable.
    from sklearn.utils.class_weight import compute_sample_weight
    sw = compute_sample_weight("balanced", ytr)
    clf.fit(Xtr, ytr, sample_weight=sw)
    acc = accuracy_score(yte, clf.predict(Xte))
    print(f"  XGBoost classifier accuracy={acc:.4f}")

    # 3) Ridge — voltage-consistency drift regressor (→ voltage_std).
    reg = Ridge(alpha=1.0)
    Xv = df[VOLTAGE_FEATURES].astype(float).values
    yv = df["voltage_std"].astype(float)
    Xvtr, Xvte, yvtr, yvte = train_test_split(Xv, yv, test_size=0.2, random_state=42)
    reg.fit(Xvtr, yvtr)
    yv_pred = reg.predict(Xvte)
    mae = mean_absolute_error(yvte, yv_pred)
    rmse = math.sqrt(mean_squared_error(yvte, yv_pred))
    print(f"  Ridge voltage regressor  MAE={mae:.5f}  RMSE={rmse:.5f}")

    joblib.dump(iso, MODEL_DIR / "battery_anomaly_detector.pkl")
    joblib.dump(clf, MODEL_DIR / "battery_risk_classifier.pkl")
    joblib.dump(reg, MODEL_DIR / "battery_voltage_regressor.pkl")
    (MODEL_DIR / "risk_encoder.json").write_text(json.dumps(RISK_ENCODER, indent=2))
    (MODEL_DIR / "cell_lot_encoder.json").write_text(json.dumps(cell_lot_encoder, indent=2))
    (MODEL_DIR / "feature_list.json").write_text(json.dumps({
        "anomaly_features": ANOMALY_FEATURES,
        "classifier_features": CLASSIFIER_FEATURES,
        "voltage_features": VOLTAGE_FEATURES,
    }, indent=2))

    print("  Saved → battery_anomaly_detector.pkl, battery_risk_classifier.pkl, "
          "battery_voltage_regressor.pkl")
    print("  Saved → feature_list.json, risk_encoder.json, cell_lot_encoder.json")

    # Anchor smoke test — PACK-07 13:20 thermal crisis.
    anchor = {"temperature": 32.2, "temperature_delta": 3.9, "voltage_std": 0.021,
              "press_force": 3.05, "cell_lot": "LOT-2026-0619"}
    a_score = float(iso.decision_function(
        np.array([[anchor["temperature"], anchor["temperature_delta"],
                   anchor["press_force"], anchor["voltage_std"]]]))[0])
    lot_enc = cell_lot_encoder.get(anchor["cell_lot"], 0)
    proba = clf.predict_proba(np.array([[anchor["temperature_delta"], anchor["voltage_std"],
                                         anchor["press_force"], lot_enc, a_score]]))[0]
    risk = {v: k for k, v in RISK_ENCODER.items()}[int(np.argmax(proba))]
    print(f"\n  Anchor PACK-07: risk={risk}  confidence={proba.max():.2f}  "
          f"anomaly_score={a_score:.3f}")
    print("\n✓ Done")


if __name__ == "__main__":
    main()
