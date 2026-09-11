"""
G1 — Verdict Lock (deterministic).

Enforces that the classification verdict (severity / defect_type) comes ONLY from
the upstream ML tool output. The LLM may report and reason about the verdict, but it
may not override it. Given the raw ML prediction JSON plus whatever the LLM proposes,
this tool returns the authoritative (locked) values and flags any override attempt.

Place this right after the ML prediction tool in the Triage agent. The returned
`severity` / `defect_type` are the only values the rest of the workflow may use.

Anti-hallucination role: kills the most dangerous failure — a fabricated or
LLM-"corrected" classification that sends the whole investigation down the wrong path.
"""

from __future__ import annotations

import json
import argparse
from typing import Optional, Any, List

from pydantic import BaseModel, Field


class UserParameters(BaseModel):
    """Registration-time config for the verdict lock."""
    allowed_severities: List[str] = Field(
        default=["HIGH", "MEDIUM", "INVESTIGATE"],
        description="Closed set of severity values the ML tool may emit; anything else is rejected.",
    )
    severity_field: str = Field(
        default="risk_level",
        description="Key in the ML output JSON that holds the authoritative severity.",
    )
    defect_field: str = Field(
        default="defect_type",
        description="Key in the ML output JSON that holds the authoritative defect type.",
    )


class ToolParameters(BaseModel):
    """Runtime arguments passed by the agent."""
    ml_output: dict = Field(
        description="Raw JSON returned by the ML prediction tool, e.g. "
        '{"risk_level":"HIGH","defect_type":"thermal_anomaly","confidence":0.93}.',
    )
    proposed_severity: Optional[str] = Field(
        default=None,
        description="Severity the LLM wants to state (optional). If it differs from the ML value it is an override attempt.",
    )
    proposed_defect_type: Optional[str] = Field(
        default=None,
        description="Defect type the LLM wants to state (optional). If it differs from the ML value it is an override attempt.",
    )
    action_on_block: str = Field(
        default="return_verdict",
        description="'raise_error' halts the task on an override attempt; 'return_verdict' returns the locked verdict so the agent can proceed with the authoritative values.",
    )


def run_tool(config: UserParameters, args: ToolParameters) -> Any:
    ml = args.ml_output or {}
    severity = ml.get(config.severity_field)
    defect_type = ml.get(config.defect_field)

    reasons: List[str] = []
    if severity is None:
        reasons.append(f"ML output missing authoritative field '{config.severity_field}'")
    elif severity not in config.allowed_severities:
        reasons.append(
            f"severity '{severity}' not in allowed set {config.allowed_severities}"
        )

    override_attempt = False
    if args.proposed_severity is not None and args.proposed_severity != severity:
        override_attempt = True
        reasons.append(
            f"LLM proposed severity '{args.proposed_severity}' != authoritative '{severity}' (ignored)"
        )
    if args.proposed_defect_type is not None and args.proposed_defect_type != defect_type:
        override_attempt = True
        reasons.append(
            f"LLM proposed defect_type '{args.proposed_defect_type}' != authoritative '{defect_type}' (ignored)"
        )

    verdict = "LOCKED"
    if reasons and severity is None:
        verdict = "INVALID_ML_OUTPUT"
    elif override_attempt:
        verdict = "OVERRIDE_BLOCKED"

    result = {
        "guardrail": "G1",
        "verdict": verdict,
        "severity": severity,          # authoritative — the only value downstream may use
        "defect_type": defect_type,    # authoritative
        "locked": True,
        "override_attempt": override_attempt,
        "reason": "; ".join(reasons) if reasons else "verdict taken verbatim from ML output",
    }

    if verdict in ("OVERRIDE_BLOCKED", "INVALID_ML_OUTPUT") and args.action_on_block == "raise_error":
        raise ValueError(json.dumps(result))

    return result


OUTPUT_KEY = "tool_output"


def _coerce_json_fields(raw: str) -> dict:
    """Agent Studio sometimes passes list/dict parameters as JSON-encoded strings.
    Parse the outer JSON, then json.loads any string value that looks like a JSON
    array/object so Pydantic receives real lists/dicts (not strings)."""
    data = json.loads(raw) or {}
    for k, v in list(data.items()):
        if isinstance(v, str):
            s = v.strip()
            if s and s[0] in "[{":
                try:
                    data[k] = json.loads(s)
                except (ValueError, TypeError):
                    pass
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-params", required=True, help="Tool configuration (JSON)")
    parser.add_argument("--tool-params", required=True, help="Tool arguments (JSON)")
    cli = parser.parse_args()

    config = UserParameters(**_coerce_json_fields(cli.user_params))
    params = ToolParameters(**_coerce_json_fields(cli.tool_params))
    print(OUTPUT_KEY, json.dumps(run_tool(config, params), ensure_ascii=False))
