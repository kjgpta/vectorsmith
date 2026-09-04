"""Render the generated evidence block in docs/conformance.md."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

START = "<!-- BEGIN GENERATED: conformance-evidence -->"
END = "<!-- END GENERATED: conformance-evidence -->"
ORDER = ("qdrant", "pgvector", "chroma", "pinecone", "weaviate", "milvus")
LABELS = {
    "qdrant": "Qdrant",
    "pgvector": "pgvector",
    "chroma": "Chroma",
    "pinecone": "Pinecone Local",
    "weaviate": "Weaviate",
    "milvus": "Milvus",
}


def render(evidence: dict[str, Any]) -> str:
    backends = evidence.get("backends") or {}
    totals = {"passed": 0, "skipped": 0, "failed": 0}
    rows = []
    for name in ORDER:
        record = backends.get(name) or {}
        results = record.get("results") or {}
        for status in totals:
            totals[status] += int(results.get(status, 0))
        rows.append(
            "| {label} | {server} | {client} | {passed} | {skipped} | {failed} |".format(
                label=LABELS[name],
                server=record.get("server", "unrecorded"),
                client=record.get("client", "unrecorded"),
                passed=int(results.get("passed", 0)),
                skipped=int(results.get("skipped", 0)),
                failed=int(results.get("failed", 0)),
            )
        )
    total = sum(totals.values())
    lines = [
        START,
        (
            f"The latest pinned local run recorded **{total} backend test instances**: "
            f"**{totals['passed']} passed**, **{totals['skipped']} capability-gated "
            f"skips**, and **{totals['failed']} failed**."
        ),
        "",
        "| Backend | Server | Client | Passed | Skipped | Failed |",
        "|---|---:|---:|---:|---:|---:|",
        *rows,
        END,
    ]
    return "\n".join(lines)


def update(document: str, block: str) -> str:
    if document.count(START) != 1 or document.count(END) != 1:
        raise ValueError("expected exactly one conformance evidence marker pair")
    before, remainder = document.split(START, 1)
    _, after = remainder.split(END, 1)
    return before + block + after


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path(".internal/phase2/conformance-evidence.json"),
    )
    parser.add_argument(
        "--document",
        type=Path,
        default=Path("docs/conformance.md"),
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    original = args.document.read_text(encoding="utf-8")
    updated = update(original, render(evidence))
    if args.check:
        return int(original != updated)
    args.document.write_text(updated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
