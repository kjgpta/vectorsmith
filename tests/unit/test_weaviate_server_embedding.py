from __future__ import annotations

from types import SimpleNamespace

import pytest

from vectorsmith_core.adapters.base import RowBatch, SearchRequest
from vectorsmith_core.adapters.weaviate import WeaviateAdapter
from vectorsmith_core.execute.single_step import _search_variants


@pytest.mark.asyncio
async def test_server_embedding_skips_client_embed() -> None:
    captured: list[SearchRequest] = []

    class Adapter:
        async def uses_server_side_embedding(self, collection: str) -> bool:
            assert collection == "docs"
            return True

        async def search(self, req: SearchRequest) -> RowBatch:
            captured.append(req)
            return RowBatch(rows=[{"_id": "one", "_score": 0.9}])

    plan = SimpleNamespace(
        mode="dense",
        alpha=0.5,
        projection=None,
        include_score=True,
        min_score=None,
        search_ef=None,
    )
    rows = await _search_variants(
        Adapter(),  # type: ignore[arg-type]
        None,
        plan,
        ["server query"],
        collection="docs",
        ir=None,
        search_limit=3,
    )

    assert rows == [{"_id": "one", "_score": 0.9}]
    assert captured[0].vector is None
    assert captured[0].query_text == "server query"


@pytest.mark.asyncio
async def test_weaviate_text_query_uses_near_text_without_vector() -> None:
    pytest.importorskip("weaviate")

    class Query:
        kwargs: dict[str, object] = {}

        def near_text(self, **kwargs: object) -> SimpleNamespace:
            self.kwargs = kwargs
            return SimpleNamespace(
                objects=[
                    SimpleNamespace(
                        uuid="one",
                        properties={"title": "result"},
                        metadata=SimpleNamespace(certainty=0.8),
                    )
                ]
            )

    query = Query()
    collection = SimpleNamespace(query=query)
    adapter = WeaviateAdapter(
        {"url": "http://unused", "embedding_mode": "server"}
    )
    adapter._client = SimpleNamespace(
        collections=SimpleNamespace(get=lambda name: collection)
    )

    batch = await adapter.search(
        SearchRequest(
            collection="docs",
            vector=None,
            query_text="server query",
            with_score=True,
        )
    )

    assert query.kwargs["query"] == "server query"
    assert batch.rows == [{"title": "result", "_id": "one", "_score": 0.8}]
