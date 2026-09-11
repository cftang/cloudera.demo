"""
G4 — Action Catalog (deterministic).

Every disposition action the Report agent wants to emit must use an action_code that
exists in the approved MES action-code catalog. Invented or free-form codes are rejected
so a hallucinated "action" can never reach the MES system. Valid actions are returned with
their canonical catalog description (the LLM's free-text description is not trusted).

Place this in the Report agent (Agent 6) before it writes the work_order actions[].

Anti-hallucination role: guards the consequential step — a made-up action isn't just
wrong text, it's a wrong operation.
"""

from __future__ import annotations

import json
import argparse
from typing import Any, Dict, List

from pydantic import BaseModel, Field


# Default approved MES action codes (reused from the body-welding lab, Story 02).
_DEFAULT_CATALOG = {
    "MES-ACT-001": "Quarantine batch",
    "MES-ACT-007": "Hold module for deep test",
    "MES-ACT-012": "Notify line supervisor",
}


class UserParameters(BaseModel):
    """Registration-time config for the action catalog."""
    mes_action_catalog: Dict[str, str] = Field(
        default=_DEFAULT_CATALOG,
        description="Approved MES action codes → canonical description. Only these codes may be emitted. "
        "In production this is sourced from the governed MES catalog rather than a literal.",
    )


class ToolParameters(BaseModel):
    """Runtime arguments passed by the agent."""
    actions: List[dict] = Field(
        description="Proposed disposition actions; each item like "
        '{"action_code":"MES-ACT-001","description":"..."}. Only action_code is authoritative.',
    )
    action_on_block: str = Field(
        default="return_verdict",
        description="'raise_error' halts if any action_code is not in the catalog; 'return_verdict' returns the report.",
    )


def run_tool(config: UserParameters, args: ToolParameters) -> Any:
    catalog = config.mes_action_catalog or {}
    valid: List[dict] = []
    invalid: List[dict] = []

    for action in args.actions:
        code = action.get("action_code")
        if code in catalog:
            valid.append({"action_code": code, "description": catalog[code]})  # canonical description
        else:
            invalid.append(
                {
                    "action_code": code,
                    "reason": f"'{code}' not in approved MES action-code catalog",
                }
            )

    result = {
        "guardrail": "G4",
        "all_valid": len(invalid) == 0,
        "valid_actions": valid,
        "invalid_actions": invalid,
        "reason": (
            "all action codes are in the approved catalog"
            if not invalid
            else f"{len(invalid)} action code(s) not in catalog — reject or replace before issuing the work order"
        ),
    }

    if invalid and args.action_on_block == "raise_error":
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
