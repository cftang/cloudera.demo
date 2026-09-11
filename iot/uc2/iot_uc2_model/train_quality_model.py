#!/usr/bin/env python3
"""
Train XGBoost quality prediction models for UC2.

Input  : ../uc2_demo_data/sensor_readings.csv    (features, narrow format)
         ../uc2_demo_data/quality_predictions.csv (labels)
Output : quality_regressor.pkl, quality_classifier.pkl, feature_list.json

Usage  : python train_quality_model.py
"""

import json
import math
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    mean_absolute_error,
    mean_squared_error,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

DATA_DIR = Path(__file__).parent.parent / "uc2_demo_data"
MODEL_DIR = Path(__file__).parent

RISK_ENCODER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "INVESTIGATE": 3}
RISK_DECODER = {v: k for k, v in RISK_ENCODER.items()}

# Canonical wide feature columns (filled with 0.0 if absent for a given machine)
FEATURES = [
    "vibration_rms",
    "temperature",
    "sound_db",
    "humidity",
    "pressure",
    "voltage",
]


def _try_xgb():
    try:
        from xgboost import XGBClassifier, XGBRegressor
        return XGBRegressor, XGBClassifier
    except ImportError:
        from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
        print("  xgboost not found — falling back to sklearn GradientBoosting")
        return GradientBoostingRegressor, GradientBoostingClassifier


def load_and_merge() -> pd.DataFrame:
    sensors = pd.read_csv(DATA_DIR / "sensor_readings.csv", parse_dates=["event_time"])
    preds = pd.read_csv(DATA_DIR / "quality_predictions.csv", parse_dates=["prediction_time"])

    # Pivot sensor_readings from narrow to wide: one row per (machine_id, event_time)
    wide = sensors.pivot_table(
        index=["event_time", "machine_id", "process_type"],
        columns="metric",
        values="value",
        aggfunc="mean",
    ).reset_index()
    wide.columns.name = None

    # Ensure all feature columns exist (fill with 0 for metrics not present on that machine)
    for col in FEATURES:
        if col not in wide.columns:
            wide[col] = 0.0
    wide[FEATURES] = wide[FEATURES].fillna(0.0)

    # Sort both for merge_asof
    wide = wide.sort_values("event_time").reset_index(drop=True)
    preds = preds.sort_values("prediction_time").reset_index(drop=True)

    frames = []
    for machine in wide["machine_id"].unique():
        w = wide[wide["machine_id"] == machine].copy()
        p = preds[preds["machine_id"] == machine][
            ["prediction_time", "defect_rate", "risk_level"]
        ].copy()
        merged = pd.merge_asof(
            w,
            p.rename(columns={"prediction_time": "event_time"}),
            on="event_time",
            tolerance=pd.Timedelta("5min"),
            direction="nearest",
        )
        frames.append(merged)

    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["defect_rate", "risk_level"]).reset_index(drop=True)
    return df


def main() -> None:
    print("=" * 60)
    print("UC2 — Train Quality Prediction Models")
    print("=" * 60)

    df = load_and_merge()
    print(f"  Merged rows: {len(df)}")

    XGBRegressor, XGBClassifier = _try_xgb()

    X = df[FEATURES].astype(float)
    y_rate = df["defect_rate"].astype(float)
    y_risk = df["risk_level"].map(RISK_ENCODER).astype(int)

    X_train, X_test, yr_train, yr_test, yk_train, yk_test = train_test_split(
        X, y_rate, y_risk, test_size=0.2, random_state=42
    )

    # Regression model — defect_rate
    reg_kwargs = {"n_estimators": 100, "random_state": 42}
    try:
        reg = XGBRegressor(**reg_kwargs, eval_metric="rmse")
    except TypeError:
        reg = XGBRegressor(**reg_kwargs)
    reg.fit(X_train, yr_train)
    yr_pred = reg.predict(X_test)
    mae = mean_absolute_error(yr_test, yr_pred)
    rmse = math.sqrt(mean_squared_error(yr_test, yr_pred))
    print(f"  Regressor  MAE={mae:.4f}  RMSE={rmse:.4f}")

    # Classifier model — risk_level
    clf_kwargs = {"n_estimators": 100, "random_state": 42}
    try:
        clf = XGBClassifier(**clf_kwargs, eval_metric="mlogloss", use_label_encoder=False)
    except TypeError:
        clf = XGBClassifier(**clf_kwargs)
    clf.fit(X_train, yk_train)
    yk_pred = clf.predict(X_test)
    acc = accuracy_score(yk_test, yk_pred)
    print(f"  Classifier accuracy={acc:.4f}")

    reg_path = MODEL_DIR / "quality_regressor.pkl"
    clf_path = MODEL_DIR / "quality_classifier.pkl"
    enc_path = MODEL_DIR / "risk_encoder.json"
    feat_path = MODEL_DIR / "feature_list.json"

    joblib.dump(reg, reg_path)
    joblib.dump(clf, clf_path)
    enc_path.write_text(json.dumps(RISK_ENCODER, indent=2))
    feat_path.write_text(json.dumps(FEATURES, indent=2))

    print(f"  Saved → {reg_path.name}, {clf_path.name}")
    print(f"  Saved → {feat_path.name}, {enc_path.name}")
    print("\n✓ Done")


if __name__ == "__main__":
    main()
