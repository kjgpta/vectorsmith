"""Built-in tools exercise the same live isolation contract as hand-written tools."""

from __future__ import annotations

from typing import Any

import pytest

from tests.conformance.conftest import BackendCase
from tests.conformance.oracle import filtered
from vectorsmith_core.api import CallContext, EnvCredentialResolver, load_project
from vectorsmith_core.execute.engine import Engine

pytestmark = [pytest.mark.conformance, pytest.mark.asyncio(loop_scope="session")]


def _connection(case: BackendCase) -> dict[str, Any]:
    values: dict[str, dict[str, Any]] = {
        "qdrant": {"backend": "qdrant", "url": "http://localhost:6333"},
        "pgvector": {
            "backend": "pgvector",
            "dsn": "${PG_DSN}",
            "table": case.collection,
            "id_column": "id",
        },
        "chroma": {"backend": "chroma", "url": "http://localhost:8000"},
        "pinecone": {
            "backend": "pinecone",
            "api_key": "pclocal",
            "host": "http://localhost:5081",
        },
        "weaviate": {"backend": "weaviate", "url": "http://localhost:8080"},
        "milvus": {"backend": "milvus", "uri": "http://localhost:19530"},
    }
    connection = values[case.name]
    connection["builtin_tools"] = {
        "semantic_search": True,
        "get_by_id": case.adapter.caps.id_lookup,
        "count": case.adapter.caps.count_with_filter,
        "list_collections": True,
    }
    connection["builtin_defaults"] = {
        "collections": [case.collection],
        "static_filters": [{"path": "tenant", "op": "eq", "value": "acme"}],
    }
    return connection


async def _engine(case: BackendCase) -> Engine:
    project = load_project(
        {
            "tds_version": "2",
            "connections": {"main": _connection(case)},
            "tools": [],
        },
        env={
            "PG_DSN": "postgresql://vectorsmith:vectorsmith@localhost:5432/vectorsmith"
        },
    )
    assert not [issue for issue in project.issues if issue.severity == "error"]
    engine = Engine(project, credential_resolver=EnvCredentialResolver({}))

    async def adapter(_: str) -> Any:
        return case.adapter

    class Embed:
        async def embed(
            self,
            texts: list[str],
            model: str,
            *,
            config: Any = None,
        ) -> list[list[float]]:
            _ = texts, model, config
            return [case.rows[0]["_embedding"]]

    engine._adapter = adapter  # type: ignore[method-assign]
    engine._embed_for = lambda _: Embed()  # type: ignore[method-assign]
    return engine


async def test_builtin_semantic_search_preserves_static_tenant(
    backend_case: BackendCase,
) -> None:
    engine = await _engine(backend_case)
    result = await engine.call(
        "search_main",
        {"query": "first invoice"},
        ctx=CallContext(request_id="conformance-search"),
    )

    assert result.rows
    assert all(row["tenant"] == "acme" for row in result.rows)


async def test_builtin_get_by_id_cannot_cross_static_tenant(
    backend_case: BackendCase,
) -> None:
    if not backend_case.adapter.caps.id_lookup:
        pytest.skip("guardrail-preserving ID lookup is not advertised")
    engine = await _engine(backend_case)
    allowed = next(row for row in backend_case.rows if row["tenant"] == "acme")
    denied = next(row for row in backend_case.rows if row["tenant"] == "other")

    allowed_result = await engine.call(
        "get_main_by_id",
        {"id": allowed["_id"]},
        ctx=CallContext(request_id="conformance-get-allowed"),
    )
    denied_result = await engine.call(
        "get_main_by_id",
        {"id": denied["_id"]},
        ctx=CallContext(request_id="conformance-get-denied"),
    )

    assert [row["_id"] for row in allowed_result.rows] == [allowed["_id"]]
    assert denied_result.rows == []


async def test_builtin_filtered_count_matches_oracle(backend_case: BackendCase) -> None:
    if not backend_case.adapter.caps.count_with_filter:
        pytest.skip("filtered count is not advertised")
    engine = await _engine(backend_case)
    result = await engine.call(
        "count_main",
        {},
        ctx=CallContext(request_id="conformance-count"),
    )

    assert result.rows == [
        {"count": len(filtered(backend_case.rows, None)) - len(backend_case.rows) // 7}
    ]


async def test_synthesized_builtins_are_read_only(backend_case: BackendCase) -> None:
    engine = await _engine(backend_case)
    plans = [
        compiled.plan
        for name, compiled in engine.project.tools.items()
        if name.endswith("_main") or "_main_" in name
        if compiled.plan is not None
    ]
    assert plans
    assert {plan.kind for plan in plans} <= {"search", "lookup", "count", "meta"}
    assert not any(
        hasattr(backend_case.adapter, method)
        for method in ("insert", "upsert", "update", "delete", "drop_collection")
    )
