#!/usr/bin/env python3
"""
Train a Random Forest RUL (Remaining Useful Life) regression model for UC1.

Input  : ../uc1_demo_data/machine_health.csv  (features)
         ../uc1_demo_data/rul_predictions.csv  (labels)
Output : rul_model.pkl, feature_list.json

Usage  : python train_rul_model.py
"""

import json
import math
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import train_test_split

DATA_DIR = Path(__file__).parent.parent / "uc1_demo_data"
MODEL_DIR = Path(__file__).parent

FEATURES = [
    "vibration_rms_x",
    "vibration_rms_y",
    "vibration_rms_z",
    "avg_rms",
    "max_rms",
    "anomaly_score",
    "health_score",
    "z_x_ratio",
    "health_slope",
]


def load_and_merge() -> pd.DataFrame:
    health = pd.read_csv(DATA_DIR / "machine_health.csv", parse_dates=["event_time"])
    rul = pd.read_csv(DATA_DIR / "rul_predictions.csv", parse_dates=["prediction_time"])

    # Sort for merge_asof
    health = health.sort_values("event_time").reset_index(drop=True)
    rul = rul.sort_values("prediction_time").reset_index(drop=True)

    # Merge each machine separately with a ±10-min tolerance
    frames = []
    for machine in health["machine_id"].unique():
        h = health[health["machine_id"] == machine].copy()
        r = rul[rul["machine_id"] == machine][["prediction_time", "rul_hours"]].copy()
        merged = pd.merge_asof(
            h,
            r.rename(columns={"prediction_time": "event_time"}),
            on="event_time",
            tolerance=pd.Timedelta("10min"),
            direction="nearest",
        )
        frames.append(merged)

    df = pd.concat(frames, ignore_index=True)

    # Interpolate missing rul_hours per machine
    df = df.sort_values(["machine_id", "event_time"]).reset_index(drop=True)
    df["rul_hours"] = df.groupby("machine_id")["rul_hours"].transform(
        lambda s: s.interpolate(method="linear").bfill().ffill()
    )
    df = df.dropna(subset=["rul_hours"]).reset_index(drop=True)
    return df


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["avg_rms"] = (df["vibration_rms_x"] + df["vibration_rms_y"] + df["vibration_rms_z"]) / 3.0
    df["max_rms"] = df[["vibration_rms_x", "vibration_rms_y", "vibration_rms_z"]].max(axis=1)
    df["z_x_ratio"] = df["vibration_rms_z"] / df["vibration_rms_x"].clip(lower=0.01)

    # Rolling 3-window slope of health_score per machine (degradation rate)
    def rolling_slope(s: pd.Series) -> pd.Series:
        slopes = []
        vals = s.values
        for i in range(len(vals)):
            window = vals[max(0, i - 2) : i + 1]
            if len(window) < 2:
                slopes.append(0.0)
            else:
                x = np.arange(len(window), dtype=float)
                slope = np.polyfit(x, window, 1)[0]
                slopes.append(float(slope))
        return pd.Series(slopes, index=s.index)

    df["health_slope"] = df.groupby("machine_id")["health_score"].transform(rolling_slope)
    return df


def main() -> None:
    print("=" * 60)
    print("UC1 — Train RUL Regression Model")
    print("=" * 60)

    df = load_and_merge()
    print(f"  Merged rows: {len(df)}")

    df = engineer_features(df)

    X = df[FEATURES].astype(float)
    y = df["rul_hours"].astype(float)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    model = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    rmse = math.sqrt(mean_squared_error(y_test, y_pred))
    print(f"  Hold-out MAE  : {mae:.2f} hours")
    print(f"  Hold-out RMSE : {rmse:.2f} hours")

    model_path = MODEL_DIR / "rul_model.pkl"
    joblib.dump(model, model_path)
    print(f"  Saved → {model_path.name}")

    feat_path = MODEL_DIR / "feature_list.json"
    feat_path.write_text(json.dumps(FEATURES, indent=2))
    print(f"  Saved → {feat_path.name}")

    print("\nFeature importances:")
    for feat, imp in sorted(
        zip(FEATURES, model.feature_importances_), key=lambda x: -x[1]
    ):
        print(f"  {feat:<22} {imp:.4f}")

    print("\n✓ Done")


if __name__ == "__main__":
    main()
