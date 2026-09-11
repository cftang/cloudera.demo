"""
G2 — Claim Citation (deterministic rule).

Every root-cause claim must carry at least one source_id that looks like a real
citation: an authoritative document clause (e.g. "SOP-THM-042 §4.2"), a queried data
row (e.g. "COA-0619:row_44"), or a named metric ("z_score=7.3"). Claims with no
source_ids, or with source_ids that match none of the accepted citation shapes, are
flagged non-compliant so the Investigator agent must fix or drop them.

Place this in the Root-Cause Investigator agent (Agent 4) after it drafts claims[].
This is a *shape* check (does each claim cite something citable) — it does NOT judge
whether the cited evidence actually supports the claim; that is G3's job.

Anti-hallucination role: blocks bare, unsourced assertions from leaving the reasoning
step at all.
"""

from __future__ import annotations

import json
import re
import argparse
from typing import Any, List

from pydantic import BaseModel, Field


# Default accepted citation shapes:
#   1. authoritative doc id, optionally with a § clause  -> SOP-THM-042 §4.2 / COA-0619
#   2. a queried data row reference                       -> COA-0619:row_44 / quality_events:row_12
#   3. a named quantitative metric                        -> z_score=7.3 / voltage_std=0.0238
_DEFAULT_PATTERNS = [
    r"^(SOP|COA|ECN|DRW|SPEC|WPS)-[A-Za-z0-9\-]+(\s*§\s*[\w.\-]+)?$",
    r":row_\d+$",
    r"^[A-Za-z_][A-Za-z0-9_]*\s*=\s*.+$",
]


class UserParameters(BaseModel):
    """Registration-time config for the citation check."""
    citation_patterns: List[str] = Field(
        default=_DEFAULT_PATTERNS,
        description="Regex list; a source_id is a valid citation if it matches ANY pattern. "
        "Defaults accept authoritative doc clauses, data-row refs, and named metrics.",
    )
    min_sources: int = Field(
        default=1,
        description="Minimum number of valid source_ids a claim must carry to be compliant.",
    )


class ToolParameters(BaseModel):
    """Runtime arguments passed by the agent."""
    claims: List[dict] = Field(
        description="Claim contract list; each item like "
        '{"claim":"...","source_ids":["SOP-THM-042 §4.2"],"confidence":0.8}.',
    )
    action_on_block: str = Field(
        default="return_verdict",
        description="'raise_error' halts the task if any claim is non-compliant; 'return_verdict' returns the per-claim report.",
    )


def _matches_any(source_id: str, compiled) -> bool:
    return any(rx.search(source_id.strip()) for rx in compiled)


def run_tool(config: UserParameters, args: ToolParameters) -> Any:
    compiled = [re.compile(p, re.IGNORECASE) for p in config.citation_patterns]

    compliant: List[dict] = []
    non_compliant: List[dict] = []

    for claim in args.claims:
        source_ids = claim.get("source_ids") or []
        valid_sources = [s for s in source_ids if isinstance(s, str) and _matches_any(s, compiled)]
        if len(valid_sources) >= config.min_sources:
            compliant.append({"claim": claim.get("claim"), "valid_source_ids": valid_sources})
        else:
            non_compliant.append(
                {
                    "claim": claim.get("claim"),
                    "source_ids": source_ids,
                    "reason": (
                        "no source_ids" if not source_ids
                        else f"{len(valid_sources)} valid citation(s), need {config.min_sources}"
                    ),
                }
            )

    result = {
        "guardrail": "G2",
        "all_compliant": len(non_compliant) == 0,
        "compliant_claims": compliant,
        "non_compliant_claims": non_compliant,
        "reason": (
            "every claim carries a valid citation"
            if not non_compliant
            else f"{len(non_compliant)} claim(s) lack a valid citation — fix or drop before synthesis"
        ),
    }

    if non_compliant and args.action_on_block == "raise_error":
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
