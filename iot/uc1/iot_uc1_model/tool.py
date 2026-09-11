"""
Agent Studio tool for the UC1 RUL Prediction Service.

Actions:
  predict_rul   — call POST /predict and return a formatted RUL assessment
  health_check  — call GET /health

Usage (CLI):
  python tool.py \
    --user-params '{"endpoint_url":"http://localhost:8080"}' \
    --tool-params '{"action":"predict_rul","machine_id":"M02","health_score":38.5,
                    "vibration_rms_x":1.06,"vibration_rms_y":1.09,"vibration_rms_z":3.69,
                    "anomaly_score":1.0}'
"""

import argparse
import json
from typing import Literal, Optional

import requests
from pydantic import BaseModel, Field


class UserParameters(BaseModel):
    endpoint_url: str = Field(
        description="Base URL of the RUL Prediction Service (e.g. https://rul-app.cloudera.site)"
    )
    api_key: Optional[str] = Field(
        default=None,
        description="Bearer token for authentication (without 'Bearer ' prefix)",
    )
    timeout_seconds: int = Field(default=60, description="HTTP timeout in seconds")


class ToolParameters(BaseModel):
    action: Literal["predict_rul", "health_check"] = Field(
        description="Action: 'predict_rul' (get RUL estimate) or 'health_check' (liveness)"
    )
    machine_id: Optional[str] = Field(
        default=None, description="Machine identifier, e.g. M02"
    )
    health_score: Optional[float] = Field(
        default=None, description="Current machine health score (0–100)"
    )
    vibration_rms_x: Optional[float] = Field(
        default=None, description="5-min avg vibration RMS X axis (mm/s)"
    )
    vibration_rms_y: Optional[float] = Field(
        default=None, description="5-min avg vibration RMS Y axis (mm/s)"
    )
    vibration_rms_z: Optional[float] = Field(
        default=None, description="5-min avg vibration RMS Z axis (mm/s)"
    )
    anomaly_score: Optional[float] = Field(
        default=None, description="Anomaly score from machine_health table (0–1)"
    )
    health_slope: Optional[float] = Field(
        default=0.0, description="Rate of health score decline per window (optional)"
    )


def _headers(api_key: Optional[str]) -> dict:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        h["Authorization"] = f"Bearer {api_key}"
    return h


def run_tool(config: UserParameters, args: ToolParameters) -> str:
    base = config.endpoint_url.rstrip("/")
    headers = _headers(config.api_key)
    timeout = config.timeout_seconds

    try:
        if args.action == "health_check":
            resp = requests.get(f"{base}/health", headers=headers, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            return (
                f"RUL Service health: {data.get('status', 'unknown')} | "
                f"model={data.get('model', '?')} | "
                f"loaded={data.get('loaded', '?')}"
            )

        # predict_rul
        required = ["health_score", "vibration_rms_x", "vibration_rms_y", "vibration_rms_z", "anomaly_score"]
        missing = [f for f in required if getattr(args, f) is None]
        if missing:
            return f"Error: missing required fields for predict_rul: {', '.join(missing)}"

        payload = {
            "machine_id": args.machine_id,
            "health_score": args.health_score,
            "vibration_rms_x": args.vibration_rms_x,
            "vibration_rms_y": args.vibration_rms_y,
            "vibration_rms_z": args.vibration_rms_z,
            "anomaly_score": args.anomaly_score,
            "health_slope": args.health_slope or 0.0,
        }
        resp = requests.post(f"{base}/predict", headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        rul = data.get("rul_hours", "?")
        risk = data.get("risk_level", "?")
        conf = data.get("confidence", "?")
        fw = data.get("feature_window", {})

        return (
            f"RUL Prediction for {args.machine_id or 'machine'}: "
            f"{rul}h remaining | risk={risk} | confidence={conf}\n"
            f"Feature window: {json.dumps(fw)}"
        )

    except requests.exceptions.RequestException as e:
        return f"RUL service request failed: {e}"
    except Exception as e:
        return f"Tool execution failed: {e}"


OUTPUT_KEY = "tool_output"

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-params", required=True)
    parser.add_argument("--tool-params", required=True)
    cli_args = parser.parse_args()

    config = UserParameters(**json.loads(cli_args.user_params))
    params = ToolParameters(**json.loads(cli_args.tool_params))
    print(OUTPUT_KEY, run_tool(config, params))
