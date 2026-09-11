#!/usr/bin/env python3
"""
FastAPI serving app for the UC1 RUL regression model.

Endpoints:
  POST /predict  — return RUL estimate given machine health features
  GET  /health   — liveness check
"""

import json
import os
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

MODEL_DIR = Path(__file__).parent

app = FastAPI(title="UC1 RUL Prediction Service", version="1.0.0")

# Loaded once at startup
_model = None
_features: list[str] = []


def _load_model():
    global _model, _features
    model_path = MODEL_DIR / "rul_model.pkl"
    feat_path = MODEL_DIR / "feature_list.json"
    if not model_path.exists():
        raise RuntimeError(
            f"Model not found: {model_path}. Run train_rul_model.py first."
        )
    _model = joblib.load(model_path)
    _features = json.loads(feat_path.read_text()) if feat_path.exists() else []


@app.on_event("startup")
def startup():
    _load_model()


def _risk_level(rul_hours: float) -> str:
    if rul_hours < 8:
        return "CRITICAL"
    if rul_hours < 24:
        return "HIGH"
    if rul_hours < 72:
        return "MEDIUM"
    return "LOW"


def _confidence(model, X: np.ndarray) -> float:
    """Estimate confidence from RF tree prediction spread."""
    preds = np.array([tree.predict(X)[0] for tree in model.estimators_])
    std = float(np.std(preds))
    mean = float(np.mean(preds))
    # Spread relative to prediction; scale to [0.70, 0.95]
    cv = std / max(mean, 1.0)
    conf = max(0.70, min(0.95, 0.95 - cv * 0.5))
    return round(conf, 3)


class PredictRequest(BaseModel):
    machine_id: Optional[str] = Field(default=None, description="Machine identifier (M01/M02/M03)")
    health_score: float = Field(..., description="Current health score (0–100)")
    vibration_rms_x: float = Field(..., description="5-min avg vibration RMS X axis (mm/s)")
    vibration_rms_y: float = Field(..., description="5-min avg vibration RMS Y axis (mm/s)")
    vibration_rms_z: float = Field(..., description="5-min avg vibration RMS Z axis (mm/s)")
    anomaly_score: float = Field(..., description="Anomaly score (0–1)")
    health_slope: float = Field(default=0.0, description="Rate of health decline (units/window)")


class PredictResponse(BaseModel):
    rul_hours: float
    confidence: float
    risk_level: str
    feature_window: dict


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    if _model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    avg_rms = (req.vibration_rms_x + req.vibration_rms_y + req.vibration_rms_z) / 3.0
    max_rms = max(req.vibration_rms_x, req.vibration_rms_y, req.vibration_rms_z)
    z_x_ratio = req.vibration_rms_z / max(req.vibration_rms_x, 0.01)

    row = {
        "vibration_rms_x": req.vibration_rms_x,
        "vibration_rms_y": req.vibration_rms_y,
        "vibration_rms_z": req.vibration_rms_z,
        "avg_rms": avg_rms,
        "max_rms": max_rms,
        "anomaly_score": req.anomaly_score,
        "health_score": req.health_score,
        "z_x_ratio": z_x_ratio,
        "health_slope": req.health_slope,
    }

    X = np.array([[row[f] for f in _features]], dtype=float)
    rul = float(_model.predict(X)[0])
    rul = max(0.0, round(rul, 1))

    return PredictResponse(
        rul_hours=rul,
        confidence=_confidence(_model, X),
        risk_level=_risk_level(rul),
        feature_window={
            "machine_id": req.machine_id,
            "health_score": round(req.health_score, 2),
            "vibration_rms_z": round(req.vibration_rms_z, 4),
            "anomaly_score": round(req.anomaly_score, 4),
            "avg_rms": round(avg_rms, 4),
        },
    )


@app.get("/health")
def health():
    return {"status": "ok", "model": "rul_regressor", "loaded": _model is not None}
