from __future__ import annotations

import sys
from collections import UserDict
from types import SimpleNamespace
from typing import Any

import pytest

from vectorsmith_core.adapters.base import SearchRequest
from vectorsmith_core.adapters.chroma import (
    ChromaAdapter,
    _chroma_rows,
    _distance_to_score,
)
from vectorsmith_core.api import load_project
from vectorsmith_core.errors import InvalidArgumentsError
from vectorsmith_core.execute.rerank import _row_text
from vectorsmith_core.ir.filter import And, Cond, Or


def test_chroma_rows_normalize_query_documents_and_scores() -> None:
    rows = _chroma_rows(
        UserDict(
            {
                "ids": [["a1", "a2"]],
                "metadatas": [[{"file_path": "a.md"}, None]],
                "documents": [["first", None]],
                "distances": [[0.0, 3.0]],
            }
        )
    )

    assert rows == [
        {
            "_id": "a1",
            "file_path": "a.md",
            "_document": "first",
            "_score": 1.0,
        },
        {"_id": "a2", "_score": 0.25},
    ]


def test_chroma_rows_normalize_flat_get_and_preserve_metadata_content() -> None:
    rows = _chroma_rows(
        {
            "ids": ["a1"],
            "metadatas": [
                {
                    "_id": "metadata-id",
                    "_document": "metadata-document",
                    "content": "metadata content",
                }
            ],
            "documents": ["Chroma document"],
            "distances": None,
        }
    )

    assert rows == [
        {
            "_id": "a1",
            "_document": "Chroma document",
            "content": "metadata content",
        }
    ]


@pytest.mark.parametrize(
    ("distance", "score"),
    [(0.0, 1.0), (1.0, 0.5), (3.0, 0.25), (-1.0, 1.0)],
)
def test_chroma_distance_becomes_higher_is_better_score(
    distance: float, score: float
) -> None:
    assert _distance_to_score(distance) == score


@pytest.mark.parametrize("distance", [None, True, "0.2", float("nan"), float("inf")])
def test_chroma_invalid_distance_is_not_exposed(distance: object) -> None:
    assert _distance_to_score(distance) is None


def test_chroma_filter_compilation_and_unsupported_operator() -> None:
    adapter = ChromaAdapter(url="http://localhost:8000")

    assert adapter.compile_filter(And(())) is None
    assert adapter.compile_filter(Or(())) is None
    assert adapter.compile_filter(
        And((Cond("tenant", "eq", "acme"), Cond("year", "gte", 2025)))
    ) == {
        "$and": [
            {"tenant": {"$eq": "acme"}},
            {"year": {"$gte": 2025}},
        ]
    }
    with pytest.raises(InvalidArgumentsError, match="does not support op 'like'"):
        adapter.compile_filter(Cond("file_path", "like", "%.md"))


class _FakeCollection:
    def __init__(self) -> None:
        self.get_calls: list[dict[str, Any]] = []
        self.query_calls: list[dict[str, Any]] = []

    async def get(self, **kwargs: Any) -> dict[str, Any]:
        self.get_calls.append(kwargs)
        return {
            "ids": ["a1"],
            "metadatas": [{"tenant": "acme", "content": "metadata content"}],
            "documents": ["document body"] if "documents" in kwargs.get("include", []) else None,
        }

    async def query(self, **kwargs: Any) -> dict[str, Any]:
        self.query_calls.append(kwargs)
        return {
            "ids": [["a1"]],
            "metadatas": [[{"tenant": "acme"}]],
            "documents": [["document body"]]
            if "documents" in kwargs.get("include", [])
            else None,
            "distances": [[0.5]] if "distances" in kwargs.get("include", []) else None,
        }


class _FakeClient:
    def __init__(self, collection: _FakeCollection) -> None:
        self.collection = collection

    async def get_collection(self, _name: str) -> _FakeCollection:
        return self.collection


@pytest.mark.asyncio
async def test_chroma_lookup_uses_record_id_and_keeps_tenant_filter() -> None:
    collection = _FakeCollection()
    adapter = ChromaAdapter(url="http://localhost:8000")

    async def fake_sdk() -> _FakeClient:
        return _FakeClient(collection)

    adapter._sdk = fake_sdk  # type: ignore[method-assign]
    result = await adapter.search(
        SearchRequest(
            collection="docs",
            filter_ir=And(
                (
                    Cond("id", "eq", "a1"),
                    Cond("tenant", "eq", "acme"),
                )
            ),
            limit=1,
            offset=2,
        )
    )

    assert collection.get_calls == [
        {
            "ids": ["a1"],
            "where": {"tenant": {"$eq": "acme"}},
            "limit": 1,
            "include": ["metadatas", "documents"],
        }
    ]
    assert result.rows[0]["_document"] == "document body"
    assert result.rows[0]["content"] == "metadata content"


@pytest.mark.asyncio
async def test_chroma_unranked_search_forwards_offset() -> None:
    collection = _FakeCollection()
    adapter = ChromaAdapter(url="http://localhost:8000")

    async def fake_sdk() -> _FakeClient:
        return _FakeClient(collection)

    adapter._sdk = fake_sdk  # type: ignore[method-assign]
    await adapter.search(SearchRequest(collection="docs", limit=5, offset=10))

    assert collection.get_calls[0]["offset"] == 10
    assert "ids" not in collection.get_calls[0]


@pytest.mark.asyncio
async def test_chroma_conflicting_lookup_ids_return_no_rows_without_query() -> None:
    collection = _FakeCollection()
    adapter = ChromaAdapter(url="http://localhost:8000")

    async def fake_sdk() -> _FakeClient:
        return _FakeClient(collection)

    adapter._sdk = fake_sdk  # type: ignore[method-assign]
    result = await adapter.search(
        SearchRequest(
            collection="docs",
            filter_ir=And((Cond("id", "eq", "a1"), Cond("id", "eq", "a2"))),
        )
    )

    assert result.rows == []
    assert collection.get_calls == []


@pytest.mark.asyncio
async def test_chroma_projection_and_include_score_control_requested_fields() -> None:
    collection = _FakeCollection()
    adapter = ChromaAdapter(url="http://localhost:8000")

    async def fake_sdk() -> _FakeClient:
        return _FakeClient(collection)

    adapter._sdk = fake_sdk  # type: ignore[method-assign]
    result = await adapter.search(
        SearchRequest(
            collection="docs",
            vector=[1.0, 0.0],
            projection=["tenant"],
            with_score=False,
        )
    )

    assert collection.query_calls[0]["include"] == ["metadatas"]
    assert "_document" not in result.rows[0]
    assert "_score" not in result.rows[0]


@pytest.mark.asyncio
async def test_chroma_rejects_invalid_filter_and_vector_offset() -> None:
    collection = _FakeCollection()
    adapter = ChromaAdapter(url="http://localhost:8000")

    async def fake_sdk() -> _FakeClient:
        return _FakeClient(collection)

    adapter._sdk = fake_sdk  # type: ignore[method-assign]
    with pytest.raises(InvalidArgumentsError, match="invalid Chroma filter"):
        await adapter.search(
            SearchRequest(collection="docs", filter_ir={"tenant": "acme"})
        )
    with pytest.raises(
        InvalidArgumentsError,
        match="does not support offsets for vector search",
    ):
        await adapter.search(
            SearchRequest(collection="docs", vector=[1.0, 0.0], offset=10)
        )

    assert collection.get_calls == []
    assert collection.query_calls == []


@pytest.mark.asyncio
async def test_chroma_https_and_bearer_auth_are_forwarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    client = object()

    async def async_http_client(**kwargs: Any) -> object:
        captured.update(kwargs)
        return client

    monkeypatch.setitem(
        sys.modules,
        "chromadb",
        SimpleNamespace(AsyncHttpClient=async_http_client),
    )
    adapter = ChromaAdapter(
        url="https://chroma.example.test",
        auth_token="secret-token",  # noqa: S106
    )

    assert await adapter._sdk() is client
    assert captured == {
        "host": "chroma.example.test",
        "port": 443,
        "ssl": True,
        "headers": {"Authorization": "Bearer secret-token"},
    }


@pytest.mark.asyncio
async def test_chroma_close_releases_async_client() -> None:
    closed = False

    class Client:
        async def close(self) -> None:
            nonlocal closed
            closed = True

    adapter = ChromaAdapter(url="http://localhost:8000")
    adapter._client = Client()

    await adapter.aclose()

    assert closed is True
    assert adapter._client is None


@pytest.mark.asyncio
async def test_chroma_filtered_count_is_paginated_and_id_count_is_native() -> None:
    calls: list[dict[str, Any]] = []

    class Collection:
        async def get(self, **kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs)
            if "ids" in kwargs:
                return {"ids": kwargs["ids"]}
            offset = kwargs["offset"]
            size = 1_000 if offset == 0 else 37
            return {"ids": [f"id-{offset + i}" for i in range(size)]}

    adapter = ChromaAdapter(url="http://localhost:8000")

    async def fake_sdk() -> _FakeClient:
        return _FakeClient(Collection())  # type: ignore[arg-type]

    adapter._sdk = fake_sdk  # type: ignore[method-assign]
    filtered = await adapter.count("docs", Cond("tenant", "eq", "acme"))
    exact = await adapter.count(
        "docs",
        And((Cond("id", "eq", "a1"), Cond("tenant", "eq", "acme"))),
    )

    assert filtered == 1_037
    assert exact == 1
    assert calls[:2] == [
        {
            "where": {"tenant": {"$eq": "acme"}},
            "limit": 1_000,
            "offset": 0,
            "include": [],
        },
        {
            "where": {"tenant": {"$eq": "acme"}},
            "limit": 1_000,
            "offset": 1_000,
            "include": [],
        },
    ]
    assert calls[2] == {
        "ids": ["a1"],
        "where": {"tenant": {"$eq": "acme"}},
        "limit": 1,
        "include": [],
    }


def test_chroma_document_precedes_metadata_content_for_reranking() -> None:
    assert (
        _row_text(
            {
                "_document": "actual document",
                "content": "metadata content",
            }
        )
        == "actual document"
    )


def test_chroma_like_is_rejected_during_validation() -> None:
    project = load_project(
        {
            "tds_version": "2",
            "connections": {
                "main": {
                    "backend": "chroma",
                    "url": "http://localhost:8000",
                }
            },
            "tools": [
                {
                    "name": "search_docs",
                    "kind": "search",
                    "description": "Search documents by their source file path.",
                    "target": {"connection": "main", "collection": "docs"},
                    "parameters": [
                        {
                            "name": "path",
                            "path": "file_path",
                            "dtype": "keyword",
                            "op": "like",
                        }
                    ],
                }
            ],
        },
        env={},
    )

    assert any(
        issue.code == "VB2004" and "does not support op 'like'" in issue.message
        for issue in project.issues
    )
