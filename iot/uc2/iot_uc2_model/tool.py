"""
Agent Studio tool for the UC2 Quality Prediction Service.

Actions:
  predict_quality  — call POST /predict and return defect risk assessment
  health_check     — call GET /health

Usage (CLI):
  python tool.py \
    --user-params '{"endpoint_url":"http://localhost:8081"}' \
    --tool-params '{"action":"predict_quality","machine_id":"BAT-01",
                    "process_type":"battery_assembly","temperature":31.9,"voltage":3.70}'
"""

import argparse
import json
from typing import Literal, Optional

import requests
from pydantic import BaseModel, Field


class UserParameters(BaseModel):
    endpoint_url: str = Field(
        description="Base URL of the Quality Prediction Service"
    )
    api_key: Optional[str] = Field(
        default=None,
        description="Bearer token for authentication (without 'Bearer ' prefix)",
    )
    timeout_seconds: int = Field(default=60, description="HTTP timeout in seconds")


class ToolParameters(BaseModel):
    action: Literal["predict_quality", "health_check"] = Field(
        description="Action: 'predict_quality' or 'health_check'"
    )
    machine_id: Optional[str] = Field(default=None, description="Machine ID (CNC-01 / PAINT-01 / BAT-01)")
    process_type: Optional[str] = Field(default=None, description="cnc / paint_booth / battery_assembly")
    vibration_rms: Optional[float] = Field(default=None, description="Vibration RMS (mm/s)")
    temperature: Optional[float] = Field(default=None, description="Temperature (celsius)")
    sound_db: Optional[float] = Field(default=None, description="Sound level (dB)")
    humidity: Optional[float] = Field(default=None, description="Humidity (percent)")
    pressure: Optional[float] = Field(default=None, description="Pressure (kPa)")
    voltage: Optional[float] = Field(default=None, description="Voltage (volts)")


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
                f"Quality Service health: {data.get('status', 'unknown')} | "
                f"model={data.get('model', '?')} | "
                f"loaded={data.get('loaded', '?')}"
            )

        # predict_quality
        payload = {
            "machine_id": args.machine_id,
            "process_type": args.process_type,
            "vibration_rms": args.vibration_rms or 0.0,
            "temperature": args.temperature or 0.0,
            "sound_db": args.sound_db or 0.0,
            "humidity": args.humidity or 0.0,
            "pressure": args.pressure or 0.0,
            "voltage": args.voltage or 0.0,
        }
        resp = requests.post(f"{base}/predict", headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        rate = data.get("defect_rate", "?")
        risk = data.get("risk_level", "?")
        conf = data.get("confidence", "?")
        fw = data.get("feature_window", {})

        return (
            f"Quality Prediction for {args.machine_id or 'machine'}: "
            f"defect_rate={rate} | risk={risk} | confidence={conf}\n"
            f"Feature window: {json.dumps(fw)}"
        )

    except requests.exceptions.RequestException as e:
        return f"Quality service request failed: {e}"
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
