"""static_filters must / must_not (bare list remains must)."""

from __future__ import annotations

from pathlib import Path

import pytest

from vectorsmith_cli.serve_common import dispatch, mcp_schemas
from vectorsmith_core.adapters.base import RowBatch
from vectorsmith_core.adapters.chroma import ChromaAdapter
from vectorsmith_core.adapters.milvus import MilvusAdapter
from vectorsmith_core.adapters.pinecone import PineconeAdapter
from vectorsmith_core.adapters.qdrant import QdrantAdapter
from vectorsmith_core.adapters.weaviate import WeaviateAdapter
from vectorsmith_core.api import CallContext, EnvCredentialResolver, load_project
from vectorsmith_core.execute.engine import Engine
from vectorsmith_core.ir.filter import And, Cond, invert_cond


def _src(static):
    return {
        "tds_version": "1",
        "connections": {"main": {"backend": "qdrant", "url": "http://localhost:6333"}},
        "tools": [
            {
                "name": "search_invoices",
                "description": "Search invoices by client status and due date for billing.",
                "target": {"connection": "main", "collection": "invoices"},
                "static_filters": static,
            }
        ],
    }


def test_bare_list_is_must_only() -> None:
    project = load_project(
        _src([{"path": "tenant", "op": "eq", "value": "acme"}]),
        env={"QDRANT_URL": "http://localhost:6333"},
    )
    plan = project.tools["search_invoices"].plan
    assert plan is not None
    assert [(c.path, c.op, c.value) for c in plan.static_must] == [
        ("tenant", "eq", "acme")
    ]
    assert plan.static_must_not == []
    assert plan.static_conds == plan.static_must


def test_must_not_compiles_and_stays_off_schema() -> None:
    project = load_project(
        _src(
            {
                "must": [{"path": "tenant", "op": "eq", "value": "acme"}],
                "must_not": [{"path": "archived", "op": "eq", "value": True}],
            }
        ),
        env={"QDRANT_URL": "http://localhost:6333"},
    )
    plan = project.tools["search_invoices"].plan
    assert plan is not None
    assert plan.static_must_not[0].path == "archived"
    schema = project.tools["search_invoices"].mcp_schema
    blob = str(schema)
    assert "archived" not in blob
    assert "must_not" not in blob
    names = [s["name"] for s in mcp_schemas(project, enable_define=False)]
    assert "search_invoices" in names


def test_vb2021_mixed_keys() -> None:
    project = load_project(
        _src(
            {
                "must": [{"path": "tenant", "op": "eq", "value": "acme"}],
                "other": True,
            }
        ),
        env={"QDRANT_URL": "http://localhost:6333"},
    )
    assert any(i.code == "VB2021" for i in project.issues)


def test_invert_cond_eq() -> None:
    assert invert_cond(Cond("archived", "eq", True)) == Cond("archived", "ne", True)


@pytest.mark.asyncio
async def test_run_tool_applies_must_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = load_project(
        _src(
            {
                "must": [{"path": "tenant", "op": "eq", "value": "acme"}],
                "must_not": [{"path": "archived", "op": "eq", "value": True}],
            }
        ),
        env={"QDRANT_URL": "http://localhost:6333"},
    )
    engine = Engine(project, credential_resolver=EnvCredentialResolver({}))
    captured: list[object] = []

    class Fake:
        def compile_filter(self, node: object) -> object:
            return node

        async def search(self, req: object) -> RowBatch:
            captured.append(getattr(req, "filter_ir", None))
            return RowBatch(rows=[], exhausted=True)

    async def _adapter(_name: str) -> Fake:
        return Fake()

    monkeypatch.setattr(engine, "_adapter", _adapter)
    await dispatch(
        engine,
        "run_tool",
        {"name": "search_invoices", "arguments": {}},
        ctx=CallContext(request_id="t"),
        enable_define=False,
        drafts_path=tmp_path / "d.yaml",
    )
    node = captured[0]
    conds: list[Cond] = []
    if isinstance(node, Cond):
        conds = [node]
    elif isinstance(node, And):
        conds = [c for c in node.children if isinstance(c, Cond)]
    assert any(c.path == "tenant" and c.value == "acme" for c in conds)
    assert any(c.path == "archived" and c.op == "ne" and c.value is True for c in conds)


def test_must_not_compiles_on_adapters() -> None:
    inverted = invert_cond(Cond("archived", "eq", True))
    q = QdrantAdapter(url="http://localhost:6333").compile_filter(inverted)
    assert isinstance(q, dict)
    assert "must_not" in q or "must" in q
    assert ChromaAdapter(url="http://localhost:8000").compile_filter(inverted) == {
        "archived": {"$ne": True}
    }
    assert PineconeAdapter(creds={}).compile_filter(inverted) == {"archived": {"$ne": True}}
    weaviate = WeaviateAdapter(creds={}).compile_filter(inverted)
    assert "target='archived'" in repr(weaviate)
    assert "NOT_EQUAL" in repr(weaviate)
    assert MilvusAdapter(creds={}).compile_filter(inverted) == "archived != True"
    pytest.importorskip("psycopg")
    from vectorsmith_core.adapters.pgvector import PgvectorAdapter
    from vectorsmith_core.tds.models import PgvectorConn

    spec = PgvectorConn(backend="pgvector", dsn="postgresql://x", table="invoices")
    compiled = PgvectorAdapter(spec, {}).compile_filter(inverted)
    assert isinstance(compiled, dict)
    assert compiled["params"] == [["archived"], True]
