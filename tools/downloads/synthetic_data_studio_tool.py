"""
Tool template for calling the Cloudera Synthetic Data Studio (SDS) REST API.

Direction 2 of the synthetic data generation workflow. Agent Studio handles schema
discovery and orchestration; this tool delegates generation and evaluation to a
deployed CAI_AMP_Synthetic_Data_Studio application via its REST API.

Supports:
- generate : POST /synthesis/freeform — produce synthetic JSON rows for one table,
             persist to output_path, return row count + FK key pool.
- evaluate : POST /synthesis/evaluate_freeform — LLM-as-judge scoring of a JSON row file.

Demo mode caps generation at 25 rows per call to keep SDS synchronous.
"""

import argparse
import csv
import json
import os
from typing import Any, Dict, List, Literal, Optional, Tuple

import requests
from pydantic import BaseModel, ConfigDict, Field

DEMO_MODE_MAX_ROWS = 500   # raised — previous 25 caused rows to always cap at SDS demo default of 10
DEFAULT_OUTPUT_DIR = "/synthetic_output"

# SDS backends accepted by /synthesis/freeform (see model_handlers.generate_response).
# Any other value makes SDS raise a 400 "Unsupported inference_type".
VALID_INFERENCE_TYPES = ("openai", "openai_compatible", "CAII", "aws_bedrock", "gemini")


class UserParameters(BaseModel):
    """
    Args:
        sds_base_url (str): Base URL of the deployed Synthetic Data Studio app.
        api_key (str): CDSW_APIV2_KEY / CDP JWT used for Bearer auth to the SDS app.
        model_id (str): Model id passed through to SDS.
        inference_type (str): SDS inference backend.
        caii_endpoint (str): Required for inference_type CAII or openai_compatible.
        timeout_seconds (int): HTTP timeout in seconds (generation can be slow).
    """

    model_config = ConfigDict(protected_namespaces=())

    sds_base_url: str = Field(
        description="Base URL of the Synthetic Data Studio application"
    )
    api_key: str = Field(description="CDSW_APIV2_KEY / CDP JWT for Bearer auth to SDS")
    model_id: str = Field(
        default="gpt-4o-mini",
        description="Model id passed through to SDS",
    )
    inference_type: str = Field(
        default="openai",
        description="SDS inference backend: openai | openai_compatible | CAII | aws_bedrock | gemini",
    )
    caii_endpoint: str = Field(
        default="",
        description="Base URL for CAII or openai_compatible inference (e.g. https://api.openai.com/v1)",
    )
    timeout_seconds: int = Field(
        default=300, description="HTTP timeout in seconds (generation can be slow)"
    )


class ToolParameters(BaseModel):
    action: Literal["generate", "evaluate"] = Field(
        description="Action: 'generate' (SDS freeform rows → JSON file) or "
        "'evaluate' (LLM-as-judge on a JSON row file)"
    )
    table_name: str = Field(
        description="Target table name, e.g. 'eda_bwc_cfmast_d_sg'"
    )
    schema_json: str = Field(
        default="",
        description="Column definitions JSON string. Required for 'generate'. "
        "Used to auto-build the evaluation rubric when eval_custom_prompt is empty.",
    )
    sample_values_json: str = Field(
        default="",
        description="Per-column distribution stats JSON string.",
    )
    num_rows: int = Field(
        default=100,
        description="Rows to generate. Pass rows_per_table from workflow inputs here — "
        "do NOT leave at default. The tool enforces a safety cap but will generate "
        "as many rows as requested up to that cap.",
    )
    dataset_name: str = Field(
        default="",
        description="Human-readable label shown in Synthetic Data Studio UI for this run "
        "(e.g. 'Customer Master - Run 1'). Defaults to table_name if empty.",
    )
    custom_prompt: str = Field(
        default="",
        description="For 'generate': additional instructions appended to the prompt.",
    )
    eval_custom_prompt: str = Field(
        default="",
        description="For 'evaluate': optional LLM-as-judge rubric override.",
    )
    eval_examples_json: str = Field(
        default="",
        description="For 'evaluate': optional [{score, justification}, ...] few-shot examples.",
    )
    output_path: str = Field(
        default="",
        description="For 'generate': JSON file path to write rows "
        "(default: /synthetic_output/<table>_synthetic.json).",
    )
    import_path: str = Field(
        default="",
        description="For 'evaluate': path to JSON row file (legacy CSV accepted). "
        "For 'generate': alias for output_path when output_path is empty.",
    )
    fk_column: str = Field(
        default="",
        description="For 'generate' on a PARENT table: column to extract as fk_key_pool "
        "after generation (e.g. cfcif). For CHILD tables with fk_values_json set, "
        "names the FK column the allowed values apply to.",
    )
    fk_values_json: str = Field(
        default="",
        description="For 'generate' on a CHILD table (single FK): JSON array of allowed "
        "values from a parent fk_key_pool. Prefer fk_constraints_json when multiple FKs.",
    )
    fk_constraints_json: str = Field(
        default="",
        description="For 'generate' on a CHILD table with multiple FKs: JSON array of "
        '{"column":"<child_fk_col>","values":["..."]} objects. Each values list comes '
        "from the matching parent fk_key_pool in the orchestrator state map.",
    )
    fk_pool_columns_json: str = Field(
        default="",
        description="For 'generate' on a PARENT table: JSON array of column names to "
        "extract as fk_key_pools after generation, e.g. [\"cfcif\",\"acct_no\"]. "
        "When omitted, falls back to fk_column for a single pool.",
    )


def _build_headers(api_key: str) -> Dict[str, str]:
    return {
        "Content-Type": "application/json",
        "accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }


def _safe_load(blob: str, default: Any) -> Any:
    if not blob:
        return default
    if isinstance(blob, (dict, list)):
        return blob
    try:
        return json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        return default


def _infer_source_system(table_name: str) -> str:
    parts = table_name.split("_")
    if len(parts) >= 2 and parts[0] == "eda":
        return parts[1].upper()
    return "UNKNOWN"


def _default_output_path(table_name: str) -> str:
    return f"{DEFAULT_OUTPUT_DIR}/{table_name}_synthetic.json"


def _resolve_output_path(args: ToolParameters) -> str:
    path = args.output_path or args.import_path or _default_output_path(args.table_name)
    if path.lower().endswith(".csv"):
        base, _ = os.path.splitext(path)
        return f"{base}.json"
    if not path.lower().endswith(".json"):
        return f"{path}.json"
    return path


def _parse_fk_constraints(args: ToolParameters) -> List[Dict[str, Any]]:
    constraints = _safe_load(args.fk_constraints_json, [])
    if isinstance(constraints, list) and constraints:
        parsed: List[Dict[str, Any]] = []
        for item in constraints:
            if not isinstance(item, dict):
                continue
            column = item.get("column")
            values = item.get("values")
            if column and isinstance(values, list) and values:
                parsed.append({"column": column, "values": values})
        if parsed:
            return parsed

    fk_values = _safe_load(args.fk_values_json, [])
    if args.fk_column and isinstance(fk_values, list) and fk_values:
        return [{"column": args.fk_column, "values": fk_values}]
    return []


def _parse_pool_columns(args: ToolParameters) -> List[str]:
    columns = _safe_load(args.fk_pool_columns_json, [])
    if isinstance(columns, list) and columns:
        return [col for col in columns if isinstance(col, str) and col]
    if args.fk_column:
        return [args.fk_column]
    return []


def _fk_constraint_lines(constraints: List[Dict[str, Any]]) -> List[str]:
    if not constraints:
        return []
    lines = ["", "Foreign key constraints (referential integrity):"]
    for item in constraints:
        column = item["column"]
        values = item["values"]
        lines += [
            f"- Column '{column}' MUST use only values from this list "
            f"(sample uniformly, reuse allowed): {json.dumps(values, ensure_ascii=False)}",
            f"- Every row's '{column}' must be exactly one of the values above.",
        ]
    return lines


def _build_generation_prompt(args: ToolParameters) -> str:
    columns = _safe_load(args.schema_json, [])
    samples = _safe_load(args.sample_values_json, {})
    source_system = _infer_source_system(args.table_name)

    lines: List[str] = [
        f"Generate {args.num_rows} rows of synthetic, PII-free tabular data for the "
        f"table '{args.table_name}' from a Singapore retail banking data lakehouse "
        f"(source system: {source_system}).",
        "",
        "Hard rules:",
        "- Return a JSON array of row objects — one object per row.",
        "- Each object MUST use exactly the column names listed below as keys.",
        "- Contain NO real customer, account, or transaction values. Use synthetic "
        "surrogate identifiers (e.g. SYN-CIF-000001) for any PII-flagged column.",
        "- Honour the declared type, observed ranges, and categorical distributions.",
        "",
        "Columns:",
    ]

    for col in columns:
        if not isinstance(col, dict):
            continue
        name = col.get("name", "?")
        ctype = col.get("type", "string")
        pii = col.get("pii_risk", False)
        rule_bits = [f"type={ctype}"]
        if pii:
            rule_bits.append("PII -> synthetic surrogate, never realistic real-world value")

        stat = samples.get(name) if isinstance(samples, dict) else None
        if isinstance(stat, dict):
            if stat.get("top_values"):
                rule_bits.append(f"sample from {stat['top_values']}")
            if stat.get("min") is not None or stat.get("max") is not None:
                rule_bits.append(f"range [{stat.get('min')}, {stat.get('max')}]")
            if stat.get("null_rate") is not None:
                rule_bits.append(f"null_rate~{stat['null_rate']}")

        lines.append(f"- {name}: {', '.join(rule_bits)}")

    lines += _fk_constraint_lines(_parse_fk_constraints(args))

    if args.custom_prompt:
        lines += ["", "Additional instructions:", args.custom_prompt]

    return "\n".join(lines)


DEFAULT_EVAL_EXAMPLES: List[Dict[str, Any]] = [
    {
        "score": 2,
        "justification": (
            "Score 2/5. The row has plausible column names but violates multiple rules: "
            "a PII column contains a realistic-looking personal name, a numeric amount is "
            "outside the expected range, and two categorical values are not from the "
            "observed distribution."
        ),
    },
    {
        "score": 3,
        "justification": (
            "Score 3/5. The row is mostly usable: types match the schema and values are "
            "syntactically valid, but business realism is mixed and one field looks "
            "like a real email domain."
        ),
    },
    {
        "score": 4,
        "justification": (
            "Score 4/5. Strong synthetic row: all columns match declared types, SG "
            "banking codes are plausible, PII columns use clear surrogates "
            "(e.g. SYN-CIF-000042)."
        ),
    },
    {
        "score": 5,
        "justification": (
            "Score 5/5. Excellent synthetic row: schema-compliant, realistic SG "
            "banking semantics, diverse values, no real-looking PII."
        ),
    },
]


def _build_evaluation_prompt(args: ToolParameters) -> str:
    if args.eval_custom_prompt.strip():
        return args.eval_custom_prompt.strip()

    columns = _safe_load(args.schema_json, [])
    samples = _safe_load(args.sample_values_json, {})
    source_system = _infer_source_system(args.table_name)

    lines: List[str] = [
        f"You are evaluating one synthetic data row from table '{args.table_name}' "
        f"(Singapore retail banking lakehouse, source system: {source_system}).",
        "",
        "Score the row 1-5 using this additive rubric:",
        "- 1: Wrong columns, invalid types, or obvious real PII leaked.",
        "- 2: Columns present but multiple type/range/category violations.",
        "- 3: Schema-compliant and mostly plausible; minor realism or PII concerns.",
        "- 4: Strong schema compliance, SG banking realism, diverse values, safe surrogates.",
        "- 5: Excellent on all criteria; clearly synthetic and production-demo quality.",
        "",
        "Check: schema compliance, business realism, diversity, PII absence.",
    ]

    pii_cols = [
        col.get("name")
        for col in columns
        if isinstance(col, dict) and col.get("pii_risk")
    ]
    if pii_cols:
        lines.append(f"PII-flagged columns requiring surrogates: {', '.join(pii_cols)}.")

    if columns:
        lines += ["", "Expected schema (name: type, constraints):"]
        for col in columns:
            if not isinstance(col, dict):
                continue
            name = col.get("name", "?")
            ctype = col.get("type", "string")
            bits = [f"type={ctype}"]
            stat = samples.get(name) if isinstance(samples, dict) else None
            if isinstance(stat, dict):
                if stat.get("top_values"):
                    bits.append(f"categories={stat['top_values']}")
                if stat.get("min") is not None or stat.get("max") is not None:
                    bits.append(f"range=[{stat.get('min')}, {stat.get('max')}]")
            lines.append(f"- {name}: {', '.join(bits)}")

    lines += [
        "",
        "Return a single overall score (1-5) and a concise justification.",
    ]
    return "\n".join(lines)


def _build_evaluation_examples(args: ToolParameters) -> List[Dict[str, Any]]:
    examples = _safe_load(args.eval_examples_json, None)
    if isinstance(examples, list) and examples:
        return examples
    return DEFAULT_EVAL_EXAMPLES


def _strip_metadata_keys(row: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in row.items() if k not in ("Topic", "Seeds", "Generated_From")}


def _extract_rows_from_sds_result(result: Any, table_name: str) -> List[Dict[str, Any]]:
    if not isinstance(result, dict):
        return []

    results = result.get("results")
    if isinstance(results, dict):
        if table_name in results and isinstance(results[table_name], list):
            return [_strip_metadata_keys(r) for r in results[table_name] if isinstance(r, dict)]
        if len(results) == 1:
            only = next(iter(results.values()))
            if isinstance(only, list):
                return [_strip_metadata_keys(r) for r in only if isinstance(r, dict)]

    return []


def _write_json_rows(path: str, rows: List[Dict[str, Any]]) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2, ensure_ascii=False)


def _csv_to_json_path(csv_path: str) -> str:
    base, _ = os.path.splitext(csv_path)
    json_path = f"{base}.json"
    with open(csv_path, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    _write_json_rows(json_path, rows)
    return json_path


def _extract_sds_export_path(result: Any) -> Optional[str]:
    """SDS returns export_path as {'local': '<file>.json'} (or a bare string).

    This is a path on the SDS app's own filesystem — the file SDS evaluate reads.
    """
    if not isinstance(result, dict):
        return None
    export_path = result.get("export_path")
    if isinstance(export_path, dict):
        return export_path.get("local") or export_path.get("s3") or None
    if isinstance(export_path, str):
        return export_path
    return None


def _resolve_eval_import_path(import_path: str) -> str:
    """Resolve the evaluate input path.

    SDS evaluate_freeform opens import_path on the SDS app filesystem, NOT on the
    Agent Studio tool host. Only convert CSV->JSON when the file happens to exist
    locally (legacy); otherwise pass the path straight through to SDS.
    """
    if os.path.exists(import_path) and import_path.lower().endswith(".csv"):
        return _csv_to_json_path(import_path)
    return import_path


def _fk_key_pool(rows: List[Dict[str, Any]], column: str) -> List[str]:
    if not column:
        return []
    seen = set()
    pool: List[str] = []
    for row in rows:
        value = row.get(column)
        if value is None or value in seen:
            continue
        seen.add(value)
        pool.append(value)
    return pool


def _demo_row_count(requested: int) -> Tuple[int, Optional[str]]:
    if requested <= DEMO_MODE_MAX_ROWS:
        return requested, None
    return DEMO_MODE_MAX_ROWS, (
        f"Requested {requested} rows but demo mode caps at {DEMO_MODE_MAX_ROWS}. "
        f"Generated {DEMO_MODE_MAX_ROWS} rows synchronously."
    )


def _extract_error_detail(response: requests.Response) -> str:
    """Pull the human-readable reason out of an SDS error response.

    SDS returns errors as JSON like {"status": "failed", "error": "..."} or
    {"detail": "..."}. On a 400 from /synthesis/freeform this usually contains
    the underlying ModelHandlerError (e.g. missing OPENAI_API_KEY, bad model_id).
    Fall back to the raw body so nothing is ever silently swallowed.
    """
    try:
        body = response.json()
    except ValueError:
        text = (response.text or "").strip()
        return text[:800] if text else "<empty response body>"

    if isinstance(body, dict):
        for key in ("error", "detail", "message"):
            value = body.get(key)
            if value:
                return str(value)[:800]
    return json.dumps(body, ensure_ascii=False)[:800]


def _post(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: int) -> Any:
    response = requests.post(
        url, headers=headers, json=payload, timeout=timeout, allow_redirects=True
    )
    if response.status_code >= 400:
        # raise_for_status() alone loses the SDS error body — surface it instead so
        # a generic "400 Bad Request" becomes an actionable message.
        detail = _extract_error_detail(response)
        raise requests.exceptions.HTTPError(
            f"{response.status_code} {response.reason} for {url} — SDS reported: {detail}",
            response=response,
        )
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}


def _build_sds_payload(
    config: UserParameters, args: ToolParameters, custom_prompt: str, num_rows: int
) -> Dict[str, Any]:
    # Use dataset_name for the Studio display label; fall back to table_name.
    # The topic is what Synthetic Data Studio shows in its UI — make it human-readable.
    display_name = args.dataset_name.strip() or args.table_name
    payload: Dict[str, Any] = {
        "use_case": "custom",
        "technique": "freeform",
        "model_id": config.model_id,
        "inference_type": config.inference_type,
        "num_questions": num_rows,
        "topics": [display_name],
        "custom_prompt": custom_prompt,
        "model_params": {
            "temperature": 0.7,
            "top_p": 1,
            "top_k": 50,
            "max_tokens": 8192,
        },
    }
    if config.caii_endpoint:
        payload["caii_endpoint"] = config.caii_endpoint

    columns = _safe_load(args.schema_json, [])
    if columns:
        example_row = {}
        for col in columns[:8]:
            if isinstance(col, dict):
                example_row[col.get("name", "col")] = "<synthetic_value>"
        if example_row:
            payload["example_custom"] = [example_row]

    return payload


def _validate_config(config: UserParameters) -> Optional[str]:
    """Catch misconfigurations that would otherwise surface as an opaque SDS 400."""
    if not config.sds_base_url.strip():
        return "Error: 'sds_base_url' is not set. Provide the SDS application URL."
    if not config.api_key.strip():
        return "Error: 'api_key' is not set. Provide your CDSW_APIV2_KEY / CDP JWT."
    if config.inference_type not in VALID_INFERENCE_TYPES:
        return (
            f"Error: inference_type='{config.inference_type}' is invalid. "
            f"Use one of: {', '.join(VALID_INFERENCE_TYPES)}. "
            "For direct OpenAI access use 'openai' and set OPENAI_API_KEY on the SDS app."
        )
    if config.inference_type in ("CAII", "openai_compatible") and not config.caii_endpoint.strip():
        return (
            f"Error: inference_type='{config.inference_type}' requires 'caii_endpoint'. "
            "For direct OpenAI access use inference_type='openai' and leave caii_endpoint empty."
        )
    return None


def handle_generate(config: UserParameters, args: ToolParameters) -> str:
    config_error = _validate_config(config)
    if config_error:
        return config_error
    if not args.schema_json:
        return "Error: 'schema_json' is required for action='generate'."

    effective_rows, row_warning = _demo_row_count(args.num_rows)
    output_path = _resolve_output_path(args)

    url = f"{config.sds_base_url.rstrip('/')}/synthesis/freeform"
    prompt = _build_generation_prompt(
        args.model_copy(update={"num_rows": effective_rows})
    )
    payload = _build_sds_payload(config, args, prompt, effective_rows)

    result = _post(url, _build_headers(config.api_key), payload, config.timeout_seconds)
    rows = _extract_rows_from_sds_result(result, args.table_name)

    if not rows:
        return json.dumps(
            {
                "action": "generate",
                "table": args.table_name,
                "requested_rows": args.num_rows,
                "effective_rows": effective_rows,
                "warning": row_warning,
                "output_path": output_path,
                "rows_written": 0,
                "error": "No rows returned from SDS — check result.errors in SDS response.",
                "result": result,
            },
            indent=2,
            ensure_ascii=False,
        )

    _write_json_rows(output_path, rows)
    pool_columns = _parse_pool_columns(args)
    fk_key_pools: Dict[str, List[str]] = {}
    for column in pool_columns:
        pool = _fk_key_pool(rows, column)
        if pool:
            fk_key_pools[column] = pool

    sds_export_path = _extract_sds_export_path(result)

    response: Dict[str, Any] = {
        "action": "generate",
        "table": args.table_name,
        "requested_rows": args.num_rows,
        "effective_rows": effective_rows,
        "rows_written": len(rows),
        "output_path": output_path,
        # SDS-side file (on the SDS app filesystem). Pass THIS as import_path to evaluate —
        # NOT output_path, which lives on the Agent Studio tool host.
        "sds_export_path": sds_export_path,
        "eval_import_path": sds_export_path,
        "result": result,
    }
    if row_warning:
        response["warning"] = row_warning
    if fk_key_pools:
        response["fk_key_pools"] = fk_key_pools
        if len(fk_key_pools) == 1:
            only_column = next(iter(fk_key_pools))
            response["fk_column"] = only_column
            response["fk_key_pool"] = fk_key_pools[only_column]

    return json.dumps(response, indent=2, ensure_ascii=False)


def handle_evaluate(config: UserParameters, args: ToolParameters) -> str:
    config_error = _validate_config(config)
    if config_error:
        return config_error
    eval_path = args.import_path or args.output_path
    if not eval_path:
        return "Error: 'import_path' is required for action='evaluate'."

    try:
        sds_import_path = _resolve_eval_import_path(eval_path)
    except FileNotFoundError as exc:
        return f"Error: {exc}"
    except (OSError, csv.Error, json.JSONDecodeError) as exc:
        return f"Error: failed to prepare evaluation input from '{eval_path}': {exc}"

    url = f"{config.sds_base_url.rstrip('/')}/synthesis/evaluate_freeform"
    prompt = _build_evaluation_prompt(args)
    examples = _build_evaluation_examples(args)
    payload: Dict[str, Any] = {
        "use_case": "custom",
        "technique": "freeform",
        "model_id": config.model_id,
        "inference_type": config.inference_type,
        "import_path": sds_import_path,
        "import_type": "local",
        "custom_prompt": prompt,
        "examples": examples,
        "is_demo": True,
        "max_workers": 4,
    }
    if config.caii_endpoint:
        payload["caii_endpoint"] = config.caii_endpoint

    result = _post(url, _build_headers(config.api_key), payload, config.timeout_seconds)

    # The eval input lives on the SDS filesystem, so it usually does not exist locally.
    # Count rows from the local file only when present; otherwise leave as null and rely
    # on the SDS result for per-row scores.
    row_count: Optional[int] = None
    if os.path.exists(sds_import_path):
        try:
            with open(sds_import_path, encoding="utf-8") as handle:
                row_count = len(_safe_load(handle.read(), []))
        except (OSError, json.JSONDecodeError):
            row_count = None

    return json.dumps(
        {
            "action": "evaluate",
            "table": args.table_name,
            "import_path": eval_path,
            "sds_import_path": sds_import_path,
            "rows_evaluated": row_count,
            "result": result,
        },
        indent=2,
        ensure_ascii=False,
    )


def run_tool(config: UserParameters, args: ToolParameters) -> str:
    try:
        if args.action == "generate":
            return handle_generate(config, args)
        if args.action == "evaluate":
            return handle_evaluate(config, args)
        return f"Error: Unsupported action '{args.action}'."
    except requests.exceptions.RequestException as e:
        return f"Synthetic Data Studio request failed: {str(e)}"
    except Exception as e:
        return f"Tool execution failed: {str(e)}"


OUTPUT_KEY = "tool_output"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-params", required=True, help="JSON string for tool configuration")
    parser.add_argument("--tool-params", required=True, help="JSON string for tool arguments")
    cli_args = parser.parse_args()

    config = UserParameters(**json.loads(cli_args.user_params))
    params = ToolParameters(**json.loads(cli_args.tool_params))

    print(OUTPUT_KEY, run_tool(config, params))
