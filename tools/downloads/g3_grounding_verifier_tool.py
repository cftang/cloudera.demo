"""
G3 — Grounding Verifier (evidence sufficiency + claim-level grounding).

Given the Investigator's claims[] and the Analyst's evidence_bundle, judge each claim:
supported / partial / conflicting / unsupported — then set the workflow response_policy
(answer_with_citations / answer_supported_only / present_conflict / abstain).

By design it sees ONLY atomic claims + independent evidence, never the upstream
reasoning prose — this avoids confirmation bias (proposal §4).

Two modes (mirrors the platform's POC → production path):
  local — deterministic rule check (POC): a claim is supported only if its source_ids
          point at an AUTHORITATIVE doc (allowlisted prefix) that is RELEASED / in the
          evidence bundle, or at a real data row. Generic distractor docs (DOC-GEN-*),
          unsourced, or OBSOLETE citations -> unsupported.
  api   — POST claims + evidence_bundle to a hosted grounding model on Cloudera AI
          Inference (NIM / NeMo-Guardrails-style) and pass its verdicts through.

Place this in the Grounding Verifier agent (Agent 5).
"""

from __future__ import annotations

import json
import argparse
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class UserParameters(BaseModel):
    """Registration-time config for the grounding verifier."""
    mode: str = Field(
        default="local",
        description="'local' — deterministic rule check (POC, no network); "
        "'api' — call a hosted grounding model on Cloudera AI Inference.",
    )
    authoritative_prefixes: List[str] = Field(
        default=["SOP-", "COA-", "ECN-", "DRW-", "SPEC-", "WPS-"],
        description="A source_id is authoritative only if it starts with one of these prefixes.",
    )
    generic_prefixes: List[str] = Field(
        default=["DOC-GEN-"],
        description="Prefixes marking generic distractor docs; citing one -> unsupported.",
    )
    require_released: bool = Field(
        default=True,
        description="If true, an authoritative doc must also appear in evidence_bundle.released_docs "
        "(or authoritative_docs) to count as supporting; otherwise it is treated as stale/OBSOLETE.",
    )
    verifier_endpoint: Optional[str] = Field(
        default=None,
        description="AI Inference base URL (required when mode='api'), e.g. 'https://caii.example.com/v1'.",
    )
    verifier_api_key: Optional[str] = Field(
        default=None,
        description="Bearer token for the AI Inference endpoint (mode='api').",
    )


class ToolParameters(BaseModel):
    """Runtime arguments passed by the agent."""
    claims: List[dict] = Field(
        description="Claim contract list; each item like "
        '{"claim":"...","source_ids":["COA-0619 §4.2","DOC-GEN-007"],"confidence":0.7}.',
    )
    evidence_bundle: dict = Field(
        default={},
        description="Independent evidence, e.g. "
        '{"authoritative_docs":["COA-0619"],"released_docs":["COA-0619"],'
        '"conflicts":[["SOP-THM-042","SOP-QUAL-028"]],"needs_clarification":false}.',
    )
    action_on_block: str = Field(
        default="return_verdict",
        description="'raise_error' halts on response_policy=abstain; 'return_verdict' returns the structured verdict.",
    )


def _is_authoritative(source_id: str, config: UserParameters) -> bool:
    return any(source_id.startswith(p) for p in config.authoritative_prefixes)


def _is_generic(source_id: str, config: UserParameters) -> bool:
    return any(source_id.startswith(p) for p in config.generic_prefixes)


def _doc_id(source_id: str) -> str:
    # "COA-0619 §4.2" / "COA-0619:row_44" -> "COA-0619"
    return source_id.split(" ")[0].split(":")[0].strip()


def _is_data_row(source_id: str) -> bool:
    return ":row_" in source_id or "=" in source_id


def _released_set(evidence_bundle: dict) -> set:
    docs = set(evidence_bundle.get("released_docs") or [])
    docs |= set(evidence_bundle.get("authoritative_docs") or [])
    return docs


def _conflict_docs(evidence_bundle: dict) -> List[set]:
    return [set(pair) for pair in (evidence_bundle.get("conflicts") or [])]


def _classify_local(claim: dict, config: UserParameters, evidence_bundle: dict) -> dict:
    source_ids = [s for s in (claim.get("source_ids") or []) if isinstance(s, str)]
    released = _released_set(evidence_bundle)
    conflicts = _conflict_docs(evidence_bundle)

    supporting: List[str] = []
    for s in source_ids:
        if _is_generic(s, config):
            continue
        if _is_data_row(s):
            supporting.append(s)
            continue
        if _is_authoritative(s, config):
            if not config.require_released or _doc_id(s) in released:
                supporting.append(s)

    cited_docs = {_doc_id(s) for s in source_ids}
    is_conflicting = any(pair.issubset(cited_docs) for pair in conflicts)

    if is_conflicting:
        status = "conflicting"
        reason = "two authoritative sources with conflicting conclusions cited"
    elif not source_ids:
        status = "unsupported"
        reason = "no source_ids"
    elif not supporting:
        status = "unsupported"
        reason = "no source_id is authoritative+released or a real data row (e.g. generic DOC-GEN / stale)"
    elif len(supporting) < len(source_ids):
        status = "partial"
        reason = "some cited sources are not authoritative evidence"
    else:
        status = "supported"
        reason = "all cited sources are authoritative+released or real data rows"

    return {
        "claim": claim.get("claim"),
        "status": status,
        "source_ids": supporting or source_ids,
        "reason": reason,
    }


def _aggregate_policy(verdicts: List[dict]) -> str:
    statuses = {v["status"] for v in verdicts}
    if any(s == "conflicting" for s in statuses):
        return "present_conflict"
    if verdicts and all(v["status"] == "supported" for v in verdicts):
        return "answer_with_citations"
    if any(v["status"] in ("supported", "partial") for v in verdicts):
        return "answer_supported_only"
    return "abstain"


def _verify_local(config: UserParameters, args: ToolParameters) -> dict:
    verdicts = [_classify_local(c, config, args.evidence_bundle) for c in args.claims]
    policy = _aggregate_policy(verdicts)
    dropped = [v["claim"] for v in verdicts if v["status"] == "unsupported"]
    citations = sorted({s for v in verdicts if v["status"] in ("supported", "partial") for s in v["source_ids"]})
    return {"verdicts": verdicts, "response_policy": policy, "dropped_claims": dropped, "citations": citations}


def _verify_api(config: UserParameters, args: ToolParameters) -> dict:
    import requests  # local import so 'local' mode has no network dependency

    if not config.verifier_endpoint:
        raise ValueError("mode='api' requires verifier_endpoint")
    headers = {"Content-Type": "application/json"}
    if config.verifier_api_key:
        headers["Authorization"] = f"Bearer {config.verifier_api_key}"
    resp = requests.post(
        f"{config.verifier_endpoint.rstrip('/')}/verify",
        headers=headers,
        json={"claims": args.claims, "evidence_bundle": args.evidence_bundle},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def run_tool(config: UserParameters, args: ToolParameters) -> Any:
    # Evidence explicitly insufficient → abstain without judging.
    if args.evidence_bundle.get("needs_clarification"):
        result = {
            "guardrail": "G3",
            "verdicts": [],
            "response_policy": "abstain",
            "dropped_claims": [c.get("claim") for c in args.claims],
            "citations": [],
            "reason": "evidence_bundle.needs_clarification=true",
        }
    else:
        core = _verify_api(config, args) if config.mode == "api" else _verify_local(config, args)
        result = {"guardrail": "G3", **core}

    if result["response_policy"] == "abstain" and args.action_on_block == "raise_error":
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
