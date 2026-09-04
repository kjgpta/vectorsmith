from __future__ import annotations

from types import SimpleNamespace

import pytest

from vectorsmith_core.adapters.base import SearchRequest
from vectorsmith_core.adapters.milvus import MilvusAdapter, _milvus_path, _milvus_score
from vectorsmith_core.adapters.pgvector import _normalize_row, _sql_clause
from vectorsmith_core.adapters.pinecone import PineconeAdapter
from vectorsmith_core.adapters.qdrant import QdrantAdapter, _match, _row, _split_lookup_id
from vectorsmith_core.adapters.weaviate import WeaviateAdapter
from vectorsmith_core.errors import InvalidArgumentsError
from vectorsmith_core.ir.filter import And, Cond


def test_qdrant_native_id_extraction_preserves_tenant_guardrail() -> None:
    point_id, remaining, impossible = _split_lookup_id(
        And((Cond("id", "eq", "point-1"), Cond("tenant", "eq", "acme")))
    )

    assert point_id == "point-1"
    assert remaining == Cond("tenant", "eq", "acme")
    assert not impossible


def test_qdrant_conflicting_native_ids_are_impossible() -> None:
    assert _split_lookup_id(
        And((Cond("id", "eq", "point-1"), Cond("id", "eq", "point-2")))
    ) == (None, None, True)


def test_qdrant_actual_id_wins_over_adversarial_payload() -> None:
    point = SimpleNamespace(id="actual", payload={"_id": "payload", "content": "ok"})
    assert _row(point, None) == {"_id": "actual", "content": "ok"}


async def test_qdrant_rejects_vector_offset_before_sdk_access() -> None:
    adapter = QdrantAdapter("http://unused")
    with pytest.raises(InvalidArgumentsError, match="offset"):
        await adapter.search(
            SearchRequest(collection="docs", vector=[1.0], offset=1)
        )


def test_qdrant_array_and_negated_null_filters() -> None:
    assert _match(Cond("tags", "contains_any", ["urgent", "paid"])) == {
        "key": "tags",
        "match": {"any": ["urgent", "paid"]},
    }
    assert _match(Cond("tags", "contains_all", ["urgent", "paid"])) == {
        "must": [
            {"key": "tags", "match": {"value": "urgent"}},
            {"key": "tags", "match": {"value": "paid"}},
        ]
    }
    assert _match(Cond("note", "is_null", False)) == {
        "must_not": [{"is_null": {"key": "note"}}]
    }


def test_pgvector_row_normalizes_distance_payload_and_projection() -> None:
    row = _normalize_row(
        {
            "_id": "alias",
            "record_id": "actual",
            "payload": {"_id": "payload", "title": "wanted", "secret": "hidden"},
            "embedding": [1.0],
            "_distance": 1.0,
        },
        id_column="record_id",
        projection=["title"],
        with_score=True,
    )

    assert row == {"title": "wanted", "_id": "actual", "_score": 0.5}


def test_pgvector_rejects_unimplemented_operator() -> None:
    pytest.importorskip("psycopg")
    with pytest.raises(InvalidArgumentsError, match="does not support"):
        _sql_clause(Cond("title", "text_match", "needle"), [], id_column="record_id")


def test_pgvector_array_filters_bind_json_path_and_values() -> None:
    pytest.importorskip("psycopg")
    params: list[object] = []
    _sql_clause(
        Cond("meta.tags", "contains_all", ["urgent", "paid"]),
        params,
        id_column="record_id",
    )
    assert params == [["meta", "tags"], ["urgent", "paid"]]


async def test_pinecone_rejects_partial_filter_only_and_count_behavior() -> None:
    adapter = PineconeAdapter({})
    with pytest.raises(InvalidArgumentsError, match="filter-only"):
        await adapter.search(SearchRequest(collection="tenant-a"))
    with pytest.raises(InvalidArgumentsError, match="filtered counts"):
        await adapter.count("tenant-a", Cond("tenant", "eq", "tenant-a"))


async def test_pinecone_projection_and_score_flags() -> None:
    class Index:
        def query(self, **kwargs: object) -> dict[str, object]:
            return {
                "matches": [
                    SimpleNamespace(
                        id="actual",
                        metadata={"_id": "payload", "title": "kept", "secret": "hidden"},
                        score=0.8,
                    )
                ]
            }

    adapter = PineconeAdapter({})
    adapter._index = Index()
    batch = await adapter.search(
        SearchRequest(
            collection="tenant-a",
            vector=[1.0],
            projection=["title"],
            with_score=False,
        )
    )

    assert batch.rows == [{"title": "kept", "_id": "actual"}]


def test_pinecone_array_filters_are_exact_and_bounded() -> None:
    adapter = PineconeAdapter({})
    assert adapter.compile_filter(
        Cond("tags", "contains_any", ["urgent", "paid"])
    ) == {"tags": {"$in": ["urgent", "paid"]}}
    assert adapter.compile_filter(
        Cond("tags", "contains_all", ["urgent", "paid"])
    ) == {
        "$and": [
            {"tags": {"$in": ["urgent"]}},
            {"tags": {"$in": ["paid"]}},
        ]
    }
    with pytest.raises(InvalidArgumentsError, match="10,000"):
        adapter.compile_filter(Cond("status", "in", list(range(10_001))))


def test_milvus_score_direction_is_explicit() -> None:
    assert _milvus_score(3.0, "L2") == 0.25
    assert _milvus_score(0.75, "COSINE") == 0.75
    assert _milvus_score(True, "COSINE") is None


def test_milvus_nested_and_array_filter_syntax() -> None:
    adapter = MilvusAdapter({"uri": "unused"})
    assert _milvus_path("meta.region.code") == 'meta["region"]["code"]'
    assert adapter.compile_filter(
        Cond("tags", "contains_all", ["urgent", "paid"])
    ) == "ARRAY_CONTAINS_ALL(tags, ['urgent', 'paid'])"


async def test_milvus_parses_filtered_count_response() -> None:
    class Client:
        def query(self, **kwargs: object) -> list[dict[str, int]]:
            assert kwargs["filter"] == "tenant == 'acme'"
            return [{"count(*)": 7}]

    adapter = MilvusAdapter({"uri": "unused"})
    adapter._client = Client()
    assert await adapter.count("docs", Cond("tenant", "eq", "acme")) == 7


async def test_weaviate_passes_filter_offset_and_projection_to_fetch() -> None:
    pytest.importorskip("weaviate")
    sentinel = object()

    class Query:
        kwargs: dict[str, object] = {}

        def fetch_objects(self, **kwargs: object) -> SimpleNamespace:
            self.kwargs = kwargs
            return SimpleNamespace(
                objects=[SimpleNamespace(uuid="actual", properties={"title": "kept"})]
            )

    query = Query()
    collection = SimpleNamespace(query=query)
    client = SimpleNamespace(collections=SimpleNamespace(get=lambda name: collection))
    adapter = WeaviateAdapter({"url": "http://unused"})
    adapter._client = client
    adapter.compile_filter = lambda node: sentinel  # type: ignore[method-assign]

    batch = await adapter.search(
        SearchRequest(
            collection="docs",
            filter_ir=Cond("tenant", "eq", "acme"),
            offset=3,
            projection=["title"],
        )
    )

    assert query.kwargs["filters"] is sentinel
    assert query.kwargs["offset"] == 3
    assert query.kwargs["return_properties"] == ["title"]
    assert batch.rows == [{"title": "kept", "_id": "actual"}]
