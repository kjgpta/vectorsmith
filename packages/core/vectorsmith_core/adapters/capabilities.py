"""Static per-backend capability flags (validator gating)."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class Capabilities:
    dense_search: bool
    ops: frozenset[str]
    nested_paths: bool
    arrays: bool
    exists_null: bool
    text_match_in_filter: bool
    filtered_ann_recall_safe: bool
    requires_explicit_index: bool
    introspection: Literal["typed", "names_only", "none"]
    server_side_embedding: bool
    scroll: bool
    count_with_filter: bool
    hybrid: bool
    score_threshold: bool = False
    hnsw_ef: bool = False
    support_level: Literal["stable", "experimental"] = "experimental"
    id_lookup: bool = True


LCD = frozenset({"eq", "ne", "gt", "gte", "lt", "lte", "in", "nin"})
ARRAY_OPS = frozenset({"contains_any", "contains_all"})

QDRANT_CAPS = Capabilities(
    dense_search=True,
    ops=LCD | ARRAY_OPS | frozenset({"exists", "is_null", "text_match"}),
    nested_paths=True,
    arrays=True,
    exists_null=True,
    text_match_in_filter=True,
    filtered_ann_recall_safe=True,
    requires_explicit_index=True,
    introspection="typed",
    server_side_embedding=False,
    scroll=True,
    count_with_filter=True,
    hybrid=True,
    score_threshold=True,
    hnsw_ef=True,
)

PGVECTOR_CAPS = Capabilities(
    dense_search=True,
    ops=LCD | ARRAY_OPS | frozenset({"exists", "is_null", "like"}),
    nested_paths=True,
    arrays=True,
    exists_null=True,
    text_match_in_filter=False,
    filtered_ann_recall_safe=True,
    requires_explicit_index=True,
    introspection="typed",
    server_side_embedding=False,
    scroll=True,
    count_with_filter=True,
    hybrid=False,
)

CHROMA_CAPS = Capabilities(
    dense_search=True,
    ops=LCD,
    nested_paths=False,
    arrays=False,
    exists_null=False,
    text_match_in_filter=False,
    filtered_ann_recall_safe=True,
    requires_explicit_index=False,
    introspection="none",
    server_side_embedding=False,
    scroll=True,
    count_with_filter=True,
    hybrid=False,
)

PINECONE_CAPS = Capabilities(
    dense_search=True,
    ops=LCD | ARRAY_OPS,
    nested_paths=False,
    arrays=True,
    exists_null=False,
    text_match_in_filter=False,
    filtered_ann_recall_safe=True,
    requires_explicit_index=False,
    introspection="none",
    server_side_embedding=False,
    scroll=False,
    count_with_filter=False,
    hybrid=False,
    id_lookup=False,
)

WEAVIATE_CAPS = Capabilities(
    dense_search=True,
    ops=LCD | ARRAY_OPS | frozenset({"like", "text_match"}),
    nested_paths=False,
    arrays=True,
    exists_null=False,
    text_match_in_filter=True,
    filtered_ann_recall_safe=True,
    requires_explicit_index=False,
    introspection="typed",
    server_side_embedding=True,
    scroll=True,
    count_with_filter=True,
    hybrid=True,
)

MILVUS_CAPS = Capabilities(
    dense_search=True,
    ops=LCD | ARRAY_OPS | frozenset({"like"}),
    nested_paths=True,
    arrays=True,
    exists_null=False,
    text_match_in_filter=False,
    filtered_ann_recall_safe=True,
    requires_explicit_index=True,
    introspection="typed",
    server_side_embedding=False,
    scroll=True,
    count_with_filter=True,
    hybrid=False,
)

CAPS_BY_BACKEND: dict[str, Capabilities] = {
    "qdrant": QDRANT_CAPS,
    "pgvector": PGVECTOR_CAPS,
    "chroma": CHROMA_CAPS,
    "pinecone": PINECONE_CAPS,
    "weaviate": WEAVIATE_CAPS,
    "milvus": MILVUS_CAPS,
}

CAPABILITY_MATRIX_BACKENDS = (
    "qdrant",
    "pgvector",
    "chroma",
    "pinecone",
    "weaviate",
    "milvus",
)
CAPABILITY_MATRIX_BACKEND_LABELS = {
    "qdrant": "Qdrant",
    "pgvector": "pgvector",
    "chroma": "Chroma",
    "pinecone": "Pinecone",
    "weaviate": "Weaviate",
    "milvus": "Milvus",
}
CAPABILITY_MATRIX_START = "<!-- BEGIN GENERATED: backend-capability-matrix -->"
CAPABILITY_MATRIX_END = "<!-- END GENERATED: backend-capability-matrix -->"


@dataclass(frozen=True)
class CapabilityMatrixRow:
    key: str
    label: str
    documented: bool = True


# This registry is the canonical mapping from capability fields to documentation rows.
# Internal rows are included so additions or changes cannot silently escape contract tests.
CAPABILITY_MATRIX_ROWS = (
    CapabilityMatrixRow("dense_search", "Dense search"),
    CapabilityMatrixRow("support_level", "Support level"),
    CapabilityMatrixRow("hybrid", "Hybrid / sparse"),
    CapabilityMatrixRow("nested_paths", "Nested payload paths"),
    CapabilityMatrixRow("exists_null", "`exists` / `is_null`"),
    CapabilityMatrixRow("like", "`like`"),
    CapabilityMatrixRow("text_match_in_filter", "`text_match` in filter"),
    CapabilityMatrixRow("count_with_filter", "Filtered count"),
    CapabilityMatrixRow("scroll", "Scroll"),
    CapabilityMatrixRow("id_lookup", "Guardrail-preserving exact-ID lookup"),
    CapabilityMatrixRow("introspection", "Introspection"),
    CapabilityMatrixRow("server_side_embedding", "Server-side embedding"),
    CapabilityMatrixRow("arrays", "Arrays", documented=False),
    CapabilityMatrixRow("score_threshold", "Score threshold", documented=False),
    CapabilityMatrixRow("hnsw_ef", "HNSW ef", documented=False),
    CapabilityMatrixRow(
        "filtered_ann_recall_safe",
        "Filtered ANN recall safe",
        documented=False,
    ),
    CapabilityMatrixRow(
        "requires_explicit_index",
        "Requires explicit index",
        documented=False,
    ),
    CapabilityMatrixRow("ops", "Filter operations", documented=False),
)


def _matrix_value(capabilities: Capabilities, key: str) -> str:
    if key == "like":
        return "yes" if "like" in capabilities.ops else "no"

    value = getattr(capabilities, key)
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, frozenset):
        return ", ".join(sorted(value))
    return str(value)


def render_capability_matrix(*, include_internal: bool = False) -> str:
    """Render the canonical backend capability matrix as Markdown."""
    backends = [CAPS_BY_BACKEND[name] for name in CAPABILITY_MATRIX_BACKENDS]
    rows = [
        "| | "
        + " | ".join(CAPABILITY_MATRIX_BACKEND_LABELS[name] for name in CAPABILITY_MATRIX_BACKENDS)
        + " |",
        "|---|" + "---|" * len(CAPABILITY_MATRIX_BACKENDS),
    ]
    for row in CAPABILITY_MATRIX_ROWS:
        if row.documented or include_internal:
            values = " | ".join(_matrix_value(item, row.key) for item in backends)
            rows.append(f"| {row.label} | {values} |")
    return "\n".join(rows)


def render_capability_matrix_block() -> str:
    """Render the generated, marked documentation block."""
    return f"{CAPABILITY_MATRIX_START}\n{render_capability_matrix()}\n{CAPABILITY_MATRIX_END}"


def update_capability_matrix_document(document: str) -> str:
    """Replace the marked capability matrix in a Markdown document."""
    if document.count(CAPABILITY_MATRIX_START) != 1 or document.count(CAPABILITY_MATRIX_END) != 1:
        raise ValueError("expected exactly one generated capability matrix marker pair")
    before, remainder = document.split(CAPABILITY_MATRIX_START, 1)
    _, after = remainder.split(CAPABILITY_MATRIX_END, 1)
    return before + render_capability_matrix_block() + after


def capability_matrix_document_is_current(document: str) -> bool:
    """Return whether a marked Markdown document matches the capability registry."""
    try:
        return update_capability_matrix_document(document) == document
    except ValueError:
        return False


def _main() -> int:
    parser = argparse.ArgumentParser(description="Render the backend capability matrix")
    parser.add_argument("document", type=Path, help="Markdown document containing markers")
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail instead of updating when the generated matrix is stale",
    )
    args = parser.parse_args()
    document = args.document.read_text()
    updated = update_capability_matrix_document(document)
    if args.check:
        return int(updated != document)
    args.document.write_text(updated)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
