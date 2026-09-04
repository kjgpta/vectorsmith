from __future__ import annotations

from types import SimpleNamespace

import pytest

from vectorsmith_core.adapters.chroma import ChromaAdapter
from vectorsmith_core.adapters.milvus import MilvusAdapter
from vectorsmith_core.adapters.pgvector import PgvectorAdapter
from vectorsmith_core.adapters.pinecone import PineconeAdapter
from vectorsmith_core.adapters.qdrant import QdrantAdapter
from vectorsmith_core.adapters.weaviate import WeaviateAdapter
from vectorsmith_core.errors import BackendUnreachable
from vectorsmith_core.tds.models import PgvectorConn

pytestmark = pytest.mark.fault


@pytest.mark.parametrize("failure", [TimeoutError("timed out"), PermissionError("denied")])
@pytest.mark.asyncio
async def test_health_failures_use_vectorsmith_error_contract(
    failure: Exception,
) -> None:
    class AsyncQdrant:
        async def get_collections(self) -> None:
            raise failure

    class AsyncChroma:
        async def heartbeat(self) -> None:
            raise failure

    class SyncClient:
        def fail(self) -> None:
            raise failure

    class BrokenPool:
        def connection(self) -> None:
            raise failure

    qdrant = QdrantAdapter("http://unused")
    qdrant._client = AsyncQdrant()
    chroma = ChromaAdapter("http://unused")
    chroma._client = AsyncChroma()
    pinecone = PineconeAdapter({})
    pinecone._index = SimpleNamespace(describe_index_stats=SyncClient().fail)
    weaviate = WeaviateAdapter({"url": "http://unused"})
    weaviate._client = SimpleNamespace(is_ready=SyncClient().fail)
    milvus = MilvusAdapter({"uri": "unused"})
    milvus._client = SimpleNamespace(list_collections=SyncClient().fail)
    pgvector = PgvectorAdapter(
        PgvectorConn(
            backend="pgvector",
            dsn="postgresql://unused",
            table="docs",
        ),
        {},
    )
    pgvector._pool = BrokenPool()

    for adapter in (qdrant, chroma, pinecone, weaviate, milvus, pgvector):
        with pytest.raises(BackendUnreachable, match=str(failure)):
            await adapter.health()


@pytest.mark.asyncio
async def test_qdrant_malformed_count_response_is_wrapped() -> None:
    class Client:
        async def count(self, **kwargs: object) -> object:
            return object()

    adapter = QdrantAdapter("http://unused")
    adapter._client = Client()
    with pytest.raises(BackendUnreachable):
        await adapter.count("docs", None)
