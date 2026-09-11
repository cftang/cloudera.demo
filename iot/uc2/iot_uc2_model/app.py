#!/usr/bin/env python3
"""
FastAPI serving app for the UC2 Quality Prediction models.

Endpoints:
  POST /predict  — return defect_rate, risk_level, confidence
  GET  /health   — liveness check
"""

import json
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

MODEL_DIR = Path(__file__).parent

RISK_DECODER = {0: "LOW", 1: "MEDIUM", 2: "HIGH", 3: "INVESTIGATE"}
FEATURES = [
    "vibration_rms",
    "temperature",
    "sound_db",
    "humidity",
    "pressure",
    "voltage",
]

app = FastAPI(title="UC2 Quality Prediction Service", version="1.0.0")

_regressor = None
_classifier = None


def _load_models():
    global _regressor, _classifier
    reg_path = MODEL_DIR / "quality_regressor.pkl"
    clf_path = MODEL_DIR / "quality_classifier.pkl"
    if not reg_path.exists() or not clf_path.exists():
        raise RuntimeError(
            "Models not found. Run train_quality_model.py first."
        )
    _regressor = joblib.load(reg_path)
    _classifier = joblib.load(clf_path)


@app.on_event("startup")
def startup():
    _load_models()


def _confidence(classifier, X: np.ndarray) -> float:
    try:
        proba = classifier.predict_proba(X)[0]
        return round(float(np.max(proba)), 3)
    except Exception:
        return 0.80


class PredictRequest(BaseModel):
    machine_id: Optional[str] = Field(default=None)
    process_type: Optional[str] = Field(default=None, description="cnc / paint_booth / battery_assembly")
    vibration_rms: Optional[float] = Field(default=0.0, description="mm/s")
    temperature: Optional[float] = Field(default=0.0, description="celsius")
    sound_db: Optional[float] = Field(default=0.0, description="dB")
    humidity: Optional[float] = Field(default=0.0, description="percent")
    pressure: Optional[float] = Field(default=0.0, description="kPa")
    voltage: Optional[float] = Field(default=0.0, description="volts")


class PredictResponse(BaseModel):
    defect_rate: float
    risk_level: str
    confidence: float
    feature_window: dict


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    if _regressor is None or _classifier is None:
        raise HTTPException(status_code=503, detail="Models not loaded")

    row = [
        req.vibration_rms or 0.0,
        req.temperature or 0.0,
        req.sound_db or 0.0,
        req.humidity or 0.0,
        req.pressure or 0.0,
        req.voltage or 0.0,
    ]
    X = np.array([row], dtype=float)

    defect_rate = float(_regressor.predict(X)[0])
    defect_rate = max(0.0, min(1.0, round(defect_rate, 4)))

    risk_code = int(_classifier.predict(X)[0])
    risk_level = RISK_DECODER.get(risk_code, "LOW")
    confidence = _confidence(_classifier, X)

    feature_window = {
        "machine_id": req.machine_id,
        "process_type": req.process_type,
        "vibration_rms": req.vibration_rms,
        "temperature": req.temperature,
        "humidity": req.humidity,
    }

    return PredictResponse(
        defect_rate=defect_rate,
        risk_level=risk_level,
        confidence=confidence,
        feature_window=feature_window,
    )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": "quality_predictor",
        "loaded": _regressor is not None and _classifier is not None,
    }
