"""
Agent Studio tool for the Story 01 Battery Quality Prediction Service.

Actions:
  predict_quality  — call POST /predict and return the risk assessment
  health_check     — call GET /health

Usage (CLI):
  python tool.py \
    --user-params '{"endpoint_url":"http://localhost:8080"}' \
    --tool-params '{"action":"predict_quality","machine_id":"PACK-07",
                    "process_type":"module_assembly","temperature":32.2,
                    "temperature_delta":3.9,"voltage_std":0.021,"press_force":3.05,
                    "dcr":0.86,"cell_lot":"LOT-2026-0619"}'
"""

import argparse
import json
from typing import Literal, Optional

import requests
from pydantic import BaseModel, Field


class UserParameters(BaseModel):
    endpoint_url: str = Field(description="Base URL of the Battery Quality Prediction Service")
    api_key: Optional[str] = Field(
        default=None,
        description="Bearer token for authentication (without 'Bearer ' prefix)",
    )
    timeout_seconds: int = Field(default=60, description="HTTP timeout in seconds")


class ToolParameters(BaseModel):
    action: Literal["predict_quality", "health_check"] = Field(
        description="Action: 'predict_quality' or 'health_check'"
    )
    machine_id: Optional[str] = Field(default=None, description="Machine ID (PACK-07 / PACK-03 / PACK-11)")
    process_type: Optional[str] = Field(default="module_assembly", description="Process type")
    temperature: Optional[float] = Field(default=None, description="Temperature (celsius)")
    temperature_delta: Optional[float] = Field(default=None, description="Temperature delta vs baseline (celsius)")
    voltage_std: Optional[float] = Field(default=None, description="Voltage dispersion (volts)")
    press_force: Optional[float] = Field(default=None, description="Press force (kN)")
    dcr: Optional[float] = Field(default=None, description="Direct current resistance (mΩ)")
    cell_lot: Optional[str] = Field(default=None, description="Incoming cell lot id")


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
                f"Battery Quality Service health: {data.get('status', 'unknown')} | "
                f"model={data.get('model', '?')} | loaded={data.get('loaded', '?')}"
            )

        payload = {
            "machine_id": args.machine_id,
            "process_type": args.process_type,
            "temperature": args.temperature or 0.0,
            "temperature_delta": args.temperature_delta or 0.0,
            "voltage_std": args.voltage_std or 0.0,
            "press_force": args.press_force or 0.0,
            "dcr": args.dcr or 0.0,
            "cell_lot": args.cell_lot,
        }
        resp = requests.post(f"{base}/predict", headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        return (
            f"Battery Quality Prediction for {args.machine_id or 'machine'}: "
            f"defect_rate={data.get('defect_rate', '?')} | risk={data.get('risk_level', '?')} | "
            f"confidence={data.get('confidence', '?')} | "
            f"defect_type={data.get('defect_type', '?')} | "
            f"anomaly_score={data.get('anomaly_score', '?')}\n"
            f"Top features: {data.get('top_features', [])}\n"
            f"Feature window: {json.dumps(data.get('feature_window', {}), ensure_ascii=False)}"
        )

    except requests.exceptions.RequestException as e:
        return f"Battery quality service request failed: {e}"
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
