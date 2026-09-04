from __future__ import annotations

from dataclasses import fields
from pathlib import Path

from vectorsmith_core.adapters.capabilities import (
    CAPABILITY_MATRIX_ROWS,
    CAPS_BY_BACKEND,
    Capabilities,
    capability_matrix_document_is_current,
    render_capability_matrix,
)
from vectorsmith_core.api import load_project

ROOT = Path(__file__).resolve().parents[2]
ORDER = ("qdrant", "pgvector", "chroma", "pinecone", "weaviate", "milvus")


def test_documented_support_matrix_is_generated_from_capabilities() -> None:
    docs = (ROOT / "docs" / "vector-stores.md").read_text()

    assert capability_matrix_document_is_current(docs)
    assert len([row for row in CAPABILITY_MATRIX_ROWS if row.documented]) == 12


def test_capability_matrix_registry_covers_public_and_internal_fields() -> None:
    registered = {row.key for row in CAPABILITY_MATRIX_ROWS}
    capability_fields = {field.name for field in fields(Capabilities)}

    assert registered - {"like"} == capability_fields
    assert {row.key for row in CAPABILITY_MATRIX_ROWS if not row.documented} == {
        "arrays",
        "score_threshold",
        "hnsw_ef",
        "filtered_ann_recall_safe",
        "requires_explicit_index",
        "ops",
    }


def test_internal_capability_rows_render_every_backend_value() -> None:
    rendered_rows = set(render_capability_matrix(include_internal=True).splitlines())
    caps = [CAPS_BY_BACKEND[name] for name in ORDER]

    for row in CAPABILITY_MATRIX_ROWS:
        values: list[str] = []
        for capability in caps:
            value = "like" in capability.ops if row.key == "like" else getattr(capability, row.key)
            if isinstance(value, bool):
                values.append("yes" if value else "no")
            elif isinstance(value, frozenset):
                values.append(", ".join(sorted(value)))
            else:
                values.append(str(value))
        assert f"| {row.label} | {' | '.join(values)} |" in rendered_rows


def test_experimental_backend_emits_one_stable_warning_per_connection() -> None:
    project = load_project(
        {
            "tds_version": "2",
            "connections": {
                "main": {
                    "backend": "chroma",
                    "url": "http://localhost:8000",
                }
            },
            "tools": [],
        },
        env={},
    )

    warnings = [issue for issue in project.issues if issue.code == "VB2024"]
    assert len(warnings) == 1
    assert warnings[0].severity == "warning"
    assert warnings[0].path == "connections.main"


def test_pinecone_guardrail_unsafe_builtins_are_rejected() -> None:
    project = load_project(
        {
            "tds_version": "2",
            "connections": {
                "main": {
                    "backend": "pinecone",
                    "host": "http://localhost:5081",
                    "api_key": "local",
                    "builtin_tools": {"get_by_id": True, "count": True},
                    "builtin_defaults": {
                        "collections": ["tenant-a"],
                        "static_filters": [{"path": "tenant", "op": "eq", "value": "tenant-a"}],
                    },
                }
            },
            "tools": [],
        },
        env={},
    )

    errors = [issue for issue in project.issues if issue.code == "VB2025"]
    assert {issue.tool for issue in errors} == {"get_main_by_id", "count_main"}
