"""Draft lifecycle invariants independent of backend availability."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from vectorsmith_cli.serve_common import _define_tool, expire_old_drafts
from vectorsmith_core.api import draft_tool, load_project, promote_draft
from vectorsmith_core.errors import TDSValidationError
from vectorsmith_core.tds.models import ToolSpec

pytestmark = pytest.mark.conformance


def _source(backend: str = "qdrant") -> dict[str, object]:
    connections: dict[str, dict[str, object]] = {
        "qdrant": {"backend": "qdrant", "url": "http://localhost:6333"},
        "pgvector": {
            "backend": "pgvector",
            "dsn": "postgresql://localhost/db",
            "table": "docs",
        },
        "chroma": {"backend": "chroma", "url": "http://localhost:8000"},
        "pinecone": {"backend": "pinecone", "api_key": "x", "host": "localhost"},
        "weaviate": {"backend": "weaviate", "url": "http://localhost:8080"},
        "milvus": {"backend": "milvus", "uri": "http://localhost:19530"},
    }
    connection = connections[backend]
    connection["builtin_defaults"] = {
        "collections": ["docs"],
        "static_filters": [{"path": "tenant", "op": "eq", "value": "acme"}],
    }
    return {"tds_version": "2", "connections": {"main": connection}, "tools": []}


def _proposal(*, op: str = "eq") -> dict[str, object]:
    return {
        "name": "search_by_status",
        "description": "Search documents by status while preserving tenant isolation.",
        "kind": "search",
        "target": {"connection": "main", "collection": "docs"},
        "parameters": [
            {
                "name": "status",
                "path": "status",
                "dtype": "keyword",
                "op": op,
            }
        ],
    }


@pytest.mark.parametrize(
    "backend",
    ["qdrant", "pgvector", "chroma", "pinecone", "weaviate", "milvus"],
)
def test_draft_is_inert_and_inherits_connection_guardrails(backend: str) -> None:
    project = load_project(_source(backend), env={})
    before = set(project.tools)

    draft = draft_tool(project, {"created_by": "test"}, _proposal())

    assert set(project.tools) == before
    assert any(
        item.path == "tenant" and item.value == "acme"
        for item in draft.spec.static_filters.must
    )


def test_approval_revalidates_against_current_backend_contract() -> None:
    pg_project = load_project(_source("pgvector"), env={})
    draft = draft_tool(pg_project, {}, _proposal(op="like"))
    assert not [issue for issue in draft.validator_issues if issue.severity == "error"]

    chroma_project = load_project(_source("chroma"), env={})
    with pytest.raises(TDSValidationError, match="draft has error"):
        promote_draft(draft, chroma_project)


def test_drafted_and_handwritten_specs_have_equivalent_models() -> None:
    project = load_project(_source(), env={})
    draft = draft_tool(project, {}, _proposal())
    promoted = promote_draft(draft, project)
    handwritten = ToolSpec.model_validate(
        {
            **_proposal(),
            "static_filters": {
                "must": [{"path": "tenant", "op": "eq", "value": "acme"}],
                "must_not": [],
            },
        }
    )

    assert promoted == handwritten


def test_only_read_only_schema_kinds_can_be_drafted() -> None:
    project = load_project(_source(), env={})
    proposal = _proposal()
    proposal["kind"] = "write"

    draft = draft_tool(project, {}, proposal)

    assert any(issue.severity == "error" for issue in draft.validator_issues)
    assert set(project.tools) == set()


def test_cap_and_expiry_are_enforced_together(tmp_path: Path) -> None:
    project = load_project(_source(), env={})
    old = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    current = datetime.now(UTC).isoformat()
    drafts_path = tmp_path / "tools.drafts.yaml"
    drafts_path.write_text(
        "drafts:\n"
        + "".join(
            f"- status: pending\n  created_at: '{old if index == 0 else current}'\n"
            f"  tool: {{name: draft_{index}}}\n"
            for index in range(11)
        )
    )

    expire_old_drafts(drafts_path)
    result = _define_tool(
        project,
        {
            "name": "search_extra",
            "description": "Search extra documents under inherited tenant controls.",
            "spec": _proposal() | {"name": "search_extra"},
        },
        drafts_path,
    )

    assert "cap" in result["message"].lower()
    assert "expired" in drafts_path.read_text()
