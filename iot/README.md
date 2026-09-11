# IoT Demo — UC1 & UC2

Standalone train and test commands for the two IoT use cases.

> All commands run from `/home/opc/code/iot`.  
> Use `/home/opc/code/.venv/bin/python3` if `python3` resolves to the wrong environment.

---

## UC1 — Predictive Maintenance

### Generate demo data
```bash
python3 uc1/uc1_demo_data/generate_demo_data_uc1.py
```

### Train RUL model
Outputs: `uc1/iot_uc1_model/rul_model.pkl`, `uc1/iot_uc1_model/feature_list.json`
```bash
python3 uc1/iot_uc1_model/train_rul_model.py
```

### Smoke test (requires app running)
```bash
# Terminal 1 — start the app
python3 uc1/iot_uc1_model/run_app.py

# Terminal 2 — call the tool
python3 uc1/iot_uc1_model/tool.py \
  --user-params '{"endpoint_url":"http://localhost:8080"}' \
  --tool-params '{"action":"predict_rul","machine_id":"M02","health_score":38.5,"vibration_rms_x":1.0617,"vibration_rms_y":1.0927,"vibration_rms_z":3.6932,"anomaly_score":1.0}'

```

Expected output: `RUL Prediction for M02: 6.5h remaining | risk=CRITICAL | confidence=0.95`

---

## UC2 — Predictive Quality

### Generate demo data
```bash
python3 uc2/uc2_demo_data/generate_demo_data_uc2.py
```

### Train quality models
Outputs: `uc2/iot_uc2_model/quality_regressor.pkl`, `quality_classifier.pkl`, `feature_list.json`, `risk_encoder.json`
```bash
python3 uc2/iot_uc2_model/train_quality_model.py
```

### Smoke test (requires app running)
```bash
# Terminal 1 — start the app
python3 uc2/iot_uc2_model/run_app.py

# Terminal 2 — call the tool
python3 uc2/iot_uc2_model/tool.py \
  --user-params '{"endpoint_url":"http://localhost:8080"}' \
  --tool-params '{"action":"predict_quality","machine_id":"CNC-01","process_type":"cnc","vibration_rms":2.1,"temperature":52.3,"sound_db":82.0}'

```

Expected output: `Quality Prediction for CNC-01: defect_rate=0.22 | risk=HIGH | confidence=0.80`

---

## Install dependencies

```bash
uv pip install --python /home/opc/code/.venv/bin/python3 \
  scikit-learn xgboost joblib pandas numpy fastapi uvicorn requests pydantic
```
