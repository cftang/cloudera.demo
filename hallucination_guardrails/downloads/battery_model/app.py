#!/usr/bin/env python3
"""
FastAPI serving app for the Story 01 Battery Quality Prediction models.

Endpoints:
  POST /predict  — return defect_rate, risk_level, anomaly_score, defect_type,
                   confidence, top_features
  GET  /health   — liveness check

Classic ML (IsolationForest + XGBoost + Ridge), not generative AI. The Agent
orchestrates and reasons; these models predict. Per guardrail G1, the returned
risk_level / defect_type are the authoritative fields the triage Agent must not override.
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

# Expected defect_rate per risk class — defect_rate is the probability-weighted
# expectation over these bands (keeps a single classifier authoritative; no 4th model).
RISK_DEFECT_WEIGHT = {"LOW": 0.03, "MEDIUM": 0.10, "INVESTIGATE": 0.12, "HIGH": 0.205}

# Canonical defect_type + top_features per risk class (see docs-reconciliation note:
# root cause is electrical-consistency / high DCR; thermal rise is the symptom).
DEFECT_TYPE = {
    "HIGH": "module_electrical_consistency_anomaly",
    "MEDIUM": "press_force_drift",
    "INVESTIGATE": "voltage_consistency_intermittent",
    "LOW": "none",
}
TOP_FEATURES = {
    "HIGH": ["temperature_delta", "voltage_std", "dcr"],
    "MEDIUM": ["press_force", "temperature_delta"],
    "INVESTIGATE": ["voltage_std", "anomaly_score"],
    "LOW": ["temperature", "voltage_std"],
}

app = FastAPI(title="Battery Quality Prediction Service", version="1.0.0")

_anomaly = None
_classifier = None
_voltage = None
_cell_lot_encoder = {}


def _load_models():
    global _anomaly, _classifier, _voltage, _cell_lot_encoder
    for name in ("battery_anomaly_detector.pkl", "battery_risk_classifier.pkl",
                 "battery_voltage_regressor.pkl"):
        if not (MODEL_DIR / name).exists():
            raise RuntimeError(f"{name} not found. Run train_battery_model.py first.")
    _anomaly = joblib.load(MODEL_DIR / "battery_anomaly_detector.pkl")
    _classifier = joblib.load(MODEL_DIR / "battery_risk_classifier.pkl")
    _voltage = joblib.load(MODEL_DIR / "battery_voltage_regressor.pkl")
    enc_path = MODEL_DIR / "cell_lot_encoder.json"
    if enc_path.exists():
        _cell_lot_encoder = json.loads(enc_path.read_text())


@app.on_event("startup")
def startup():
    _load_models()


class PredictRequest(BaseModel):
    machine_id: Optional[str] = Field(default=None)
    process_type: Optional[str] = Field(default="module_assembly")
    temperature: Optional[float] = Field(default=0.0, description="celsius")
    temperature_delta: Optional[float] = Field(default=0.0, description="celsius vs baseline")
    voltage_std: Optional[float] = Field(default=0.0, description="volts (dispersion)")
    press_force: Optional[float] = Field(default=0.0, description="kN")
    dcr: Optional[float] = Field(default=0.0, description="direct current resistance, mΩ")
    cell_lot: Optional[str] = Field(default=None, description="incoming cell lot id")


class PredictResponse(BaseModel):
    defect_rate: float
    risk_level: str
    anomaly_score: float
    defect_type: str
    confidence: float
    top_features: list
    feature_window: dict


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    if _anomaly is None or _classifier is None:
        raise HTTPException(status_code=503, detail="Models not loaded")

    temp = req.temperature or 0.0
    tdelta = req.temperature_delta or 0.0
    vstd = req.voltage_std or 0.0
    press = req.press_force or 0.0

    # IsolationForest anomaly score: [temperature, temperature_delta, press_force, voltage_std]
    anomaly_score = round(float(_anomaly.decision_function(
        np.array([[temp, tdelta, press, vstd]], dtype=float))[0]), 4)

    lot_enc = float(_cell_lot_encoder.get(req.cell_lot, 0))
    # Classifier: [temperature_delta, voltage_std, press_force, cell_lot_enc, anomaly_score]
    X = np.array([[tdelta, vstd, press, lot_enc, anomaly_score]], dtype=float)
    proba = _classifier.predict_proba(X)[0]
    risk_code = int(np.argmax(proba))
    risk_level = RISK_DECODER.get(risk_code, "LOW")
    confidence = round(float(np.max(proba)), 3)

    # defect_rate = probability-weighted expectation over the per-class defect bands.
    defect_rate = round(float(sum(
        proba[c] * RISK_DEFECT_WEIGHT[RISK_DECODER[c]] for c in range(len(proba))
    )), 4)

    feature_window = {
        "machine_id": req.machine_id,
        "process_type": req.process_type,
        "temperature_delta": tdelta,
        "voltage_std": vstd,
        "press_force": press,
        "dcr": req.dcr,
        "cell_lot": req.cell_lot,
    }

    return PredictResponse(
        defect_rate=defect_rate,
        risk_level=risk_level,
        anomaly_score=anomaly_score,
        defect_type=DEFECT_TYPE.get(risk_level, "none"),
        confidence=confidence,
        top_features=TOP_FEATURES.get(risk_level, []),
        feature_window=feature_window,
    )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": "battery_quality_predictor",
        "loaded": _anomaly is not None and _classifier is not None and _voltage is not None,
    }
