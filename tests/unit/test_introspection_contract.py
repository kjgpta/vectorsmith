from __future__ import annotations

from types import SimpleNamespace

from vectorsmith_core.adapters.milvus import _milvus_dtype
from vectorsmith_core.adapters.pgvector import _pg_dtype
from vectorsmith_core.adapters.qdrant import _qdrant_dtype
from vectorsmith_core.adapters.weaviate import (
    WeaviateAdapter,
    _weaviate_dtype,
    _weaviate_fields,
)
from vectorsmith_core.introspect.types import merge_fields


def test_native_dtype_mappers_use_public_contract_names() -> None:
    assert _qdrant_dtype(SimpleNamespace(data_type="integer")) == "integer"
    assert _pg_dtype("ARRAY", "_text") == "keyword[]"
    assert _weaviate_dtype("DataType.NUMBER_ARRAY") == "keyword[]"
    assert _milvus_dtype("DataType.FLOAT_VECTOR") == "unknown"


def test_native_fields_override_sample_types_but_keep_statistics() -> None:
    merged = merge_fields(
        [
            {
                "path": "amount",
                "dtype": "float",
                "nullable": False,
                "indexed": True,
            }
        ],
        [
            {
                "path": "amount",
                "dtype": "integer",
                "null_rate": 0.0,
                "examples": [10],
            },
            {"path": "sample_only", "dtype": "keyword", "null_rate": 0.5},
        ],
    )

    assert merged == [
        {
            "path": "amount",
            "dtype": "float",
            "null_rate": 0.0,
            "examples": [10],
            "provenance": "native",
            "nullable": False,
            "indexed": True,
        },
        {
            "path": "sample_only",
            "dtype": "keyword",
            "null_rate": 0.5,
            "provenance": "sample",
        },
    ]


async def test_weaviate_embedding_mode_requires_native_vectorizer() -> None:
    adapter = WeaviateAdapter(
        {"url": "http://unused", "embedding_mode": "auto"}
    )
    adapter._native_cache["docs"] = {
        "self_provided": False,
        "vectorizer": "text2vec-transformers",
    }
    assert await adapter.uses_server_side_embedding("docs")


def test_weaviate_nested_properties_are_flattened_with_provenance() -> None:
    nested = SimpleNamespace(
        name="region",
        data_type="DataType.TEXT",
        index_filterable=True,
        index_searchable=False,
        nested_properties=[],
    )
    parent = SimpleNamespace(
        name="meta",
        data_type="DataType.OBJECT",
        index_filterable=False,
        index_searchable=False,
        nested_properties=[nested],
    )

    fields = _weaviate_fields([parent])
    assert [field["path"] for field in fields] == ["meta", "meta.region"]
    assert fields[1]["indexed"] is True
