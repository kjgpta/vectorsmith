"""query.min_score / query.ef (search quality)."""

from __future__ import annotations

from typing import Any

import pytest

from vectorsmith_core.adapters.base import RowBatch, SearchRequest
from vectorsmith_core.api import CallContext, load_project
from vectorsmith_core.execute.single_step import execute_single


def _src(*, backend: str = "qdrant", **query: Any) -> dict[str, Any]:
    conn: dict[str, Any] = {"backend": backend}
    if backend == "qdrant":
        conn["url"] = "http://localhost:6333"
    elif backend == "chroma":
        conn["url"] = "http://localhost:8000"
    q: dict[str, Any] = {"param": "query", **query}
    return {
        "tds_version": "1",
        "connections": {"main": conn},
        "tools": [
            {
                "name": "search_invoices",
                "description": "Search invoices by client status and due date for billing.",
                "target": {"connection": "main", "collection": "invoices"},
                "query": q,
            }
        ],
    }


def test_min_score_and_ef_on_qdrant_plan() -> None:
    project = load_project(
        _src(min_score=0.35, ef=128),
        env={"QDRANT_URL": "http://localhost:6333"},
    )
    plan = project.tools["search_invoices"].plan
    assert plan is not None
    assert plan.min_score == 0.35
    assert plan.search_ef == 128
    assert not any(i.code in {"VB2022", "VB2023"} for i in project.issues)


def test_min_score_zero_is_kept() -> None:
    project = load_project(
        _src(min_score=0.0),
        env={"QDRANT_URL": "http://localhost:6333"},
    )
    plan = project.tools["search_invoices"].plan
    assert plan is not None
    assert plan.min_score == 0.0
    assert not any(i.code == "VB2022" for i in project.issues)


def test_vb2022_min_score_range() -> None:
    project = load_project(
        _src(min_score=1.5),
        env={"QDRANT_URL": "http://localhost:6333"},
    )
    assert any(i.code == "VB2022" for i in project.issues)


def test_ef_on_chroma_warns() -> None:
    project = load_project(_src(backend="chroma", ef=64), env={})
    assert any(i.code == "VB2023" and i.severity == "warning" for i in project.issues)
    assert not any(i.code == "VB2023" and i.severity == "error" for i in project.issues)


def test_min_score_on_chroma_warns() -> None:
    project = load_project(_src(backend="chroma", min_score=0.2), env={})
    assert any(i.code == "VB2004" and "min_score" in i.message for i in project.issues)


@pytest.mark.asyncio
async def test_results_below_min_score_dropped() -> None:
    project = load_project(
        _src(min_score=0.5),
        env={"QDRANT_URL": "http://localhost:6333"},
    )
    compiled = project.tools["search_invoices"]
    plan = compiled.plan
    assert plan is not None
    captured: list[SearchRequest] = []

    class Fake:
        async def search(self, req: SearchRequest) -> RowBatch:
            captured.append(req)
            return RowBatch(
                rows=[
                    {"invoice_id": "low", "_score": 0.1},
                    {"invoice_id": "hi", "_score": 0.9},
                ]
            )

        def compile_filter(self, node: object) -> object:
            return node

    class Embed:
        async def embed(self, texts: list[str], model: str, *, config: Any = None):
            return [[0.0] * 3]

    out = await execute_single(
        compiled,
        plan,
        {"query": "x"},
        adapter=Fake(),  # type: ignore[arg-type]
        embed=Embed(),  # type: ignore[arg-type]
        ctx=CallContext(request_id="t"),
    )
    assert captured[0].min_score == 0.5
    ids = [r["invoice_id"] for r in out.rows]
    assert ids == ["hi"]


@pytest.mark.asyncio
async def test_qdrant_passes_score_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    from types import SimpleNamespace

    class SearchParams:
        def __init__(self, hnsw_ef: int | None = None, **_: Any) -> None:
            self.hnsw_ef = hnsw_ef

    class Filter:
        def __init__(self, **_: Any) -> None:
            pass

    fake_qm = SimpleNamespace(SearchParams=SearchParams, Filter=Filter)
    fake_http = SimpleNamespace(models=fake_qm)
    monkeypatch.setitem(sys.modules, "qdrant_client", SimpleNamespace(http=fake_http))
    monkeypatch.setitem(sys.modules, "qdrant_client.http", fake_http)
    monkeypatch.setitem(sys.modules, "qdrant_client.http.models", fake_qm)

    from vectorsmith_core.adapters.qdrant import QdrantAdapter

    seen: dict[str, Any] = {}

    class Client:
        async def query_points(self, **kwargs: Any) -> Any:
            seen.update(kwargs)

            class R:
                points: list[Any] = []

            return R()

    adapter = QdrantAdapter(url="http://localhost:6333")
    monkeypatch.setattr(adapter, "_sdk", lambda: Client())
    await adapter.search(
        SearchRequest(
            collection="invoices",
            vector=[0.1, 0.2],
            min_score=0.35,
            search_ef=128,
        )
    )
    assert seen["score_threshold"] == 0.35
    assert seen["search_params"].hnsw_ef == 128


@pytest.mark.asyncio
async def test_qdrant_hybrid_passes_hnsw_ef(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    from types import SimpleNamespace

    class Value:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    class SearchParams(Value):
        pass

    class FusionQuery(Value):
        pass

    fake_qm = SimpleNamespace(
        SearchParams=SearchParams,
        Prefetch=Value,
        SparseVector=Value,
        FusionQuery=FusionQuery,
        Fusion=SimpleNamespace(RRF="rrf"),
    )
    fake_http = SimpleNamespace(models=fake_qm)
    monkeypatch.setitem(sys.modules, "qdrant_client", SimpleNamespace(http=fake_http))
    monkeypatch.setitem(sys.modules, "qdrant_client.http", fake_http)
    monkeypatch.setitem(sys.modules, "qdrant_client.http.models", fake_qm)

    from vectorsmith_core.adapters.qdrant import QdrantAdapter

    seen: dict[str, Any] = {}

    class Client:
        async def query_points(self, **kwargs: Any) -> Any:
            seen.update(kwargs)
            return SimpleNamespace(points=[])

    adapter = QdrantAdapter(url="http://localhost:6333")
    monkeypatch.setattr(
        adapter,
        "_sparse_vector",
        lambda text: SimpleNamespace(indices=[1], values=[1.0]),
    )
    await adapter._hybrid_search(
        Client(),
        SearchRequest(
            collection="invoices",
            vector=[0.1, 0.2],
            query_text="invoice one",
            mode="hybrid",
            search_ef=96,
        ),
        None,
    )

    assert seen["search_params"].hnsw_ef == 96
    assert seen["prefetch"][1].using == "text"
