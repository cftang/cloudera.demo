#!/usr/bin/env python3
"""
Expand document_metadata.csv into an ingestible RAG knowledge-base corpus.

The lab's document_metadata.csv carries each KB doc's title + summary + tags, but the actual
document bodies aren't shipped. This writes one text file per row into kb_docs/ so you can point
RAG Studio (or any retriever) at a real folder — preserving the authoritative-vs-generic split the
G2/G3 guardrails rely on (authoritative = SOP-/COA-/ECN-/DRW-/SPEC-/WPS- prefixes; generic = DOC-GEN-).

Usage:  python generate_kb_docs.py          # -> battery_demo_data/kb_docs/*.md
Self-test: python generate_kb_docs.py --check
"""

import argparse
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
CSV_PATH = HERE / "document_metadata.csv"
OUT_DIR = HERE / "kb_docs"
AUTHORITATIVE_PREFIXES = ("SOP-", "COA-", "ECN-", "DRW-", "SPEC-", "WPS-")


def is_authoritative(doc_id: str) -> bool:
    return doc_id.startswith(AUTHORITATIVE_PREFIXES)


def _tags(raw: str) -> str:
    try:
        return ", ".join(json.loads(raw)) if raw else ""
    except (json.JSONDecodeError, TypeError):
        return raw or ""


def build():
    OUT_DIR.mkdir(exist_ok=True)
    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    auth = generic = 0
    for r in rows:
        doc_id = r["doc_id"]
        authoritative = is_authoritative(doc_id)
        auth += authoritative
        generic += not authoritative
        body = (
            f"# {r.get('title', doc_id)}\n\n"
            f"- doc_id: {doc_id}\n"
            f"- classification: {'AUTHORITATIVE' if authoritative else 'GENERIC (non-authoritative)'}\n"
            f"- source_type: {r.get('source_type', '')}\n"
            f"- created_date: {r.get('created_date', '')}\n"
            f"- ocr_processed: {r.get('ocr_processed', '')}\n"
            f"- tags: {_tags(r.get('tags', ''))}\n"
            f"- source_uri: {r.get('uri', '')}\n\n"
            f"## Content\n\n{r.get('summary', '').strip() or '(no summary provided)'}\n"
        )
        (OUT_DIR / f"{doc_id}.md").write_text(body, encoding="utf-8")

    print(f"wrote {len(rows)} docs to {OUT_DIR}  (authoritative={auth}, generic={generic})")
    return len(rows), auth, generic


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="build then assert the corpus is sane")
    args = ap.parse_args()
    total, auth, generic = build()
    if args.check:
        assert total > 0, "no docs written"
        assert auth >= 4, f"expected >=4 authoritative docs, got {auth}"
        assert generic >= 1, "expected at least one generic distractor"
        assert len(list(OUT_DIR.glob("*.md"))) == total, "file count mismatch"
        print("self-check OK ✅")


if __name__ == "__main__":
    sys.exit(main())
