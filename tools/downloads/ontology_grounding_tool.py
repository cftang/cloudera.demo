"""
Ontology Grounding (prevention layer — canonical entity resolution + term disambiguation).

Runs BEFORE the agent queries data. Given a colloquial entity ("MOD-07", "module 7")
and/or a colloquial term ("material", "stock"), it (1) resolves the entity to a canonical
part_number, (2) disambiguates the term to a canonical property in the current business
context, and (3) emits a *constrained* query_plan — a parameterised SELECT against a
governed semantic view (v_part_semantic / v_quality_events_semantic), always filtered to
status='RELEASED'. It NEVER executes SQL; hand the emitted SELECT to nl-to-sql-tool /
iceberg-mcp-server to run.

This is the "prevent-first" layer of the thesis (proposal §3): cut off wrong-entity and
misread-term hallucination at the source, so the LLM can only ask the governed layer for
things the ontology (TBox) actually defines.

Disambiguation is deterministic (context-keyed dict lookup, no LLM). A polysemous term with
no resolving context returns ambiguous=true — the agent must ask a clarifying question
rather than guess (Lab 04 Case C). The SQL is a constrained SELECT against a governed view
(never free-form) so it cannot wander off-ontology.

The ontology (TBox) is read from a bundled, git-versioned ontology.yaml. Because Agent
Studio runs the tool with cwd=<workflow_dir> (not the tool dir), the path is anchored on
Path(__file__).parent; set UserParameters.ontology_config_path to an absolute path to
override with an external/governed TBox at registration time without editing this file.

Place this on the Data Analyst agent (Agent 3), ahead of nl-to-sql-tool (Lab 04 Step 2).
"""

from __future__ import annotations

import json
import argparse
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field


class UserParameters(BaseModel):
    """Registration-time config for the ontology grounding tool."""
    ontology_config_path: str = Field(
        default="ontology.yaml",
        description="Path to the TBox/ontology YAML. Absolute path -> a file you uploaded into the "
        "CML project (via the Files browser / JupyterLab), e.g. "
        "'/home/cdsw/studio-data/ontologies/ontology.yaml'; relative path -> the copy bundled beside "
        "tool.py. Upload once, point this here, and edit the file in place to update the ontology.",
    )
    database: str = Field(
        default="iot_car_battery_db",
        description="Impala database qualifying the governed views in the emitted SQL.",
    )
    default_context: Optional[str] = Field(
        default=None,
        description="Fallback business context (e.g. 'MES','ERP','WMS') used to disambiguate a "
        "polysemous term when the call supplies no context.",
    )


class ToolParameters(BaseModel):
    """Runtime arguments passed by the agent."""
    entity: Optional[str] = Field(
        default=None,
        description="Colloquial entity to resolve, e.g. 'MOD-07' / 'module 7' / 'bracket #07'.",
    )
    term: Optional[str] = Field(
        default=None,
        description="Colloquial term/property to disambiguate, e.g. 'material' / 'stock' / 'batch'.",
    )
    context: Optional[str] = Field(
        default=None,
        description="Business context that disambiguates a polysemous term, e.g. 'ERP','WMS','MES'.",
    )
    question: Optional[str] = Field(
        default=None,
        description="Optional original natural-language question, echoed back for traceability.",
    )
    action_on_block: str = Field(
        default="return_verdict",
        description="'raise_error' halts on ambiguous term or unknown entity; "
        "'return_verdict' returns the structured grounding result.",
    )


def _load_ontology(config: UserParameters) -> dict:
    # Absolute -> a YAML uploaded into the CML project (durable artefact). Relative ->
    # the bundled copy; anchored on the tool dir since Agent Studio runs cwd=<workflow_dir>.
    p = Path(config.ontology_config_path)
    if not p.is_absolute():
        p = Path(__file__).parent / p
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _norm(s: str) -> str:
    return " ".join(s.strip().lower().split())


def _resolve_entity(entity: str, ontology: dict) -> dict:
    """Colloquial entity -> canonical part_number via the alias map. Deterministic."""
    entities = ontology.get("entities") or {}
    needle = _norm(entity)
    for canonical_key, spec in entities.items():
        candidates = [canonical_key, spec.get("canonical_part_number", "")]
        candidates += spec.get("aliases", []) or []
        if any(needle == _norm(c) for c in candidates if c):
            return {
                "resolved": True,
                "canonical_entity": spec.get("canonical_part_number", canonical_key),
                "matched_alias": entity,
                "target_view": spec.get("target_view"),
                "status_filter": spec.get("status_filter"),
            }
    return {"resolved": False, "canonical_entity": None, "matched_alias": entity,
            "target_view": None, "status_filter": None}


def _disambiguate_term(term: str, context: Optional[str], ontology: dict) -> dict:
    """Colloquial term -> canonical property. Context-keyed dict lookup; no LLM.

    Two glossary entry shapes (matching Lab 04 Step 2b):
      single-sense:  {property: <col>, view: <view>}       -> resolves directly
      polysemous:    {contexts: {ERP: colA, WMS: colB}}     -> needs a matching context
    A polysemous term with no resolving context -> ambiguous=true.
    """
    glossary = ontology.get("glossary") or {}
    entry = glossary.get(term) or glossary.get(_norm(term))
    if entry is None:
        return {"ambiguous": False, "canonical_property": None, "term_view": None,
                "reason": f"term '{term}' not in glossary — treated as free term"}

    contexts = entry.get("contexts")
    if contexts:  # polysemous
        if context and context in contexts:
            return {"ambiguous": False, "canonical_property": contexts[context],
                    "term_view": entry.get("view"), "context_used": context, "reason": None}
        return {"ambiguous": True, "canonical_property": None, "term_view": entry.get("view"),
                "candidates": contexts,
                "reason": f"'{term}' is polysemous across {list(contexts)}; "
                          f"no resolving context supplied — ask for clarification"}

    return {"ambiguous": False, "canonical_property": entry.get("property"),
            "term_view": entry.get("view"), "reason": None}


def _build_query_plan(database: str, target_view: str, canonical_entity: Optional[str],
                      canonical_property: Optional[str], ontology: dict) -> Optional[dict]:
    """Emit a constrained SELECT against a governed view. Built only from resolved canonical
    values (never raw user text), so it cannot wander off-ontology. Never executed here."""
    views = ontology.get("views") or {}
    vspec = views.get(target_view)
    if not vspec:
        return None

    key_column = vspec.get("key_column")
    status_column = vspec.get("status_column")
    columns = vspec.get("columns") or []

    select_cols = []
    if key_column:
        select_cols.append(key_column)
    if canonical_property and canonical_property in columns and canonical_property not in select_cols:
        select_cols.append(canonical_property)
    if not select_cols:
        select_cols = ["*"]

    require_status = (ontology.get("axioms") or {}).get("require_status", "RELEASED")
    filters = []
    if canonical_entity and key_column:
        filters.append(f"{key_column} = '{canonical_entity}'")
    if status_column and require_status:
        filters.append(f"{status_column} = '{require_status}'")

    fqn = f"{database}.{target_view}"
    sql = f"SELECT {', '.join(select_cols)} FROM {fqn}"
    if filters:
        sql += " WHERE " + " AND ".join(filters)

    note = None
    if canonical_property and canonical_property not in columns:
        note = (f"property '{canonical_property}' is not a column of {target_view}; "
                f"it may live in another governed view — projection omitted")

    return {"target_view": fqn, "filters": filters, "sql": sql, "note": note}


def run_tool(config: UserParameters, args: ToolParameters) -> Any:
    ontology = _load_ontology(config)
    default_view = ontology.get("default_view", "v_part_semantic")

    ent = _resolve_entity(args.entity, ontology) if args.entity else {
        "resolved": None, "canonical_entity": None, "matched_alias": None,
        "target_view": None, "status_filter": None}

    ctx = args.context or config.default_context
    term = _disambiguate_term(args.term, ctx, ontology) if args.term else {
        "ambiguous": False, "canonical_property": None, "term_view": None, "reason": None}

    # A blocked grounding = we cannot safely name what to query.
    unknown_entity = args.entity is not None and ent["resolved"] is False
    blocked = bool(term.get("ambiguous")) or unknown_entity

    # Pick the governed view: term's view > entity's view > default.
    target_view = term.get("term_view") or ent.get("target_view") or default_view

    query_plan = None
    if not blocked:
        query_plan = _build_query_plan(
            config.database, target_view, ent.get("canonical_entity"),
            term.get("canonical_property"), ontology,
        )

    reasons = [r for r in (ent.get("reason") if not ent["resolved"] else None,
                           term.get("reason")) if r]
    if unknown_entity:
        reasons.insert(0, f"entity '{args.entity}' is not in the ontology — do not guess; "
                          f"resolve via the part registry or ask")

    result = {
        "layer": "prevention/ontology-grounding",
        "resolved": ent["resolved"],
        "canonical_entity": ent["canonical_entity"],
        "matched_alias": ent["matched_alias"],
        "canonical_property": term.get("canonical_property"),
        "ambiguous": bool(term.get("ambiguous")),
        "target_view": target_view,
        "query_plan": query_plan,
        "question": args.question,
        "reason": "; ".join(reasons) if reasons else "grounded to canonical entity/property",
    }
    if term.get("ambiguous"):
        result["candidates"] = term.get("candidates")

    if blocked and args.action_on_block == "raise_error":
        raise ValueError(json.dumps(result, ensure_ascii=False))

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
