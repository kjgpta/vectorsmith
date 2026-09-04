"""Hidden tenant Cond compiles on every adapter (no live store)."""

from __future__ import annotations

import pytest

from vectorsmith_core.adapters.chroma import ChromaAdapter
from vectorsmith_core.adapters.milvus import MilvusAdapter
from vectorsmith_core.adapters.pinecone import PineconeAdapter
from vectorsmith_core.adapters.qdrant import QdrantAdapter
from vectorsmith_core.adapters.weaviate import WeaviateAdapter
from vectorsmith_core.ir.filter import And, Cond

TENANT = Cond("tenant", "eq", "acme")
AND_STATUS = And((TENANT, Cond("status", "eq", "paid")))


def test_qdrant_tenant_filter() -> None:
    native = QdrantAdapter(url="http://localhost:6333").compile_filter(AND_STATUS)
    assert isinstance(native, dict)
    must = native["must"]
    assert any(item.get("key") == "tenant" for item in must)


def test_chroma_tenant_filter() -> None:
    native = ChromaAdapter(url="http://localhost:8000").compile_filter(TENANT)
    assert native == {"tenant": {"$eq": "acme"}}


def test_pinecone_tenant_filter() -> None:
    native = PineconeAdapter(creds={}).compile_filter(TENANT)
    assert native == {"tenant": {"$eq": "acme"}}


def test_weaviate_tenant_filter() -> None:
    native = WeaviateAdapter(creds={}).compile_filter(TENANT)
    assert "target='tenant'" in repr(native)
    assert "value='acme'" in repr(native)


def test_milvus_tenant_filter() -> None:
    native = MilvusAdapter(creds={}).compile_filter(TENANT)
    assert native == "tenant == 'acme'"


def test_pgvector_tenant_filter() -> None:
    pytest.importorskip("psycopg")
    from vectorsmith_core.adapters.pgvector import PgvectorAdapter
    from vectorsmith_core.tds.models import PgvectorConn

    spec = PgvectorConn(backend="pgvector", dsn="postgresql://x", table="invoices")
    compiled = PgvectorAdapter(spec, {}).compile_filter(TENANT)
    assert isinstance(compiled, dict)
    assert compiled["params"] == [["tenant"], "acme"]
