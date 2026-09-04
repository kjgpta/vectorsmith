"""Opt-in deterministic live-backend conformance fixtures."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from tests.conformance.dataset import generate_docs, payload_for
from vectorsmith_core.adapters.base import VectorBackendAdapter
from vectorsmith_core.adapters.chroma import ChromaAdapter
from vectorsmith_core.adapters.milvus import MilvusAdapter
from vectorsmith_core.adapters.pgvector import PgvectorAdapter
from vectorsmith_core.adapters.pinecone import PineconeAdapter
from vectorsmith_core.adapters.qdrant import QdrantAdapter
from vectorsmith_core.adapters.weaviate import WeaviateAdapter
from vectorsmith_core.tds.models import PgvectorConn

BACKENDS = ("qdrant", "pgvector", "chroma", "pinecone", "weaviate", "milvus")
COLLECTION = "VectorsmithConformance"
SERVER_EMBED_COLLECTION = "VectorsmithServerEmbedding"
CAPABILITY_TEST_FILES = {
    "test_arrays.py": "arrays",
    "test_nested_paths.py": "nested_paths",
    "test_introspection_contract.py": "introspection",
    "test_server_embedding.py": "server_side_embedding",
    "test_pinecone_lcd.py": "comparison_filters",
    "test_pgvector_table_mode.py": "pgvector_table_mode",
}


@dataclass
class BackendCase:
    name: str
    collection: str
    adapter: VectorBackendAdapter
    rows: list[dict[str, Any]]
    versions: dict[str, str]


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("vectorsmith-conformance")
    group.addoption(
        "--backend",
        action="append",
        choices=(*BACKENDS, "all"),
        default=[],
        help="live backend to test; repeat or use 'all'",
    )


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "backend_name" not in metafunc.fixturenames:
        return
    selected = metafunc.config.getoption("--backend")
    names = list(BACKENDS) if "all" in selected else list(dict.fromkeys(selected))
    metafunc.parametrize("backend_name", names, indirect=True, scope="session")


@pytest.fixture(scope="session")
def backend_name(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def pytest_configure(config: pytest.Config) -> None:
    config._vectorsmith_evidence = {  # type: ignore[attr-defined]
        "started_at": time.time(),
        "evidence_kind": "live",
        "client_generation": os.getenv("VECTORSMITH_CLIENT_GENERATION", "pinned"),
        "backends": {},
    }


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    evidence = session.config._vectorsmith_evidence  # type: ignore[attr-defined]
    if not evidence["backends"]:
        return
    evidence.update(
        {
            "exit_status": exitstatus,
            "duration_seconds": round(time.time() - evidence["started_at"], 3),
            "tests_collected": session.testscollected,
            "tests_failed": session.testsfailed,
        }
    )
    root = Path(__file__).resolve().parents[2]
    generation = str(evidence.get("client_generation") or "pinned")
    backend_names = sorted(evidence["backends"])
    if generation == "pinned":
        filename = "conformance-evidence.json"
    elif len(backend_names) == 1:
        filename = f"conformance-evidence-{backend_names[0]}-{generation}.json"
    else:
        filename = f"conformance-evidence-{generation}.json"
    destination = root / ".internal" / "phase2" / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item,
    call: pytest.CallInfo[None],
) -> Any:
    outcome = yield
    report = outcome.get_result()
    if (
        report.when != "call"
        and not (report.when == "setup" and report.skipped)
    ) or not hasattr(item, "callspec"):
        return
    backend = item.callspec.params.get("backend_name")
    evidence = getattr(item.config, "_vectorsmith_evidence", None)
    if backend not in BACKENDS or not evidence:
        return
    record = evidence["backends"].get(backend)
    if record is None:
        return
    results = record["results"]
    status = "skipped" if report.skipped else "failed" if report.failed else "passed"
    results[status] += 1
    results["duration_seconds"] += report.duration
    if report.failed:
        results["failures"].append(
            {"test": report.nodeid, "detail": str(report.longrepr)}
        )
    capability = next(
        (
            name
            for filename, name in CAPABILITY_TEST_FILES.items()
            if filename in report.nodeid
        ),
        None,
    )
    if "test_qdrant_hybrid_sparse_ranking_and_ef" in report.nodeid:
        capability = "hybrid_sparse"
    if capability is not None:
        proof = record["capability_proofs"].setdefault(
            capability,
            {"passed": 0, "failed": 0, "skipped": 0},
        )
        proof[status] += 1


async def _retry(factory: Callable[[], Any], *, attempts: int = 30) -> Any:
    last: Exception | None = None
    for _ in range(attempts):
        try:
            value = factory()
            return await value if asyncio.iscoroutine(value) else value
        except Exception as exc:  # backend startup is eventually consistent
            last = exc
            await asyncio.sleep(1)
    assert last is not None
    raise last


def _weaviate_vector_create_kwargs(
    configure: Any,
    *,
    server: bool,
) -> dict[str, Any]:
    vectors = getattr(configure, "Vectors", None)
    if vectors is not None:
        config = (
            vectors.text2vec_transformers()
            if server
            else vectors.self_provided()
        )
        return {"vector_config": config}
    config = (
        configure.Vectorizer.text2vec_transformers()
        if server
        else configure.Vectorizer.none()
    )
    return {"vectorizer_config": config}


@pytest_asyncio.fixture(scope="session")
async def backend_case(
    backend_name: str,
    request: pytest.FixtureRequest,
) -> AsyncIterator[BackendCase]:
    rows = generate_docs()
    if backend_name == "qdrant":
        case, cleanup = await _qdrant_case(rows)
    elif backend_name == "pgvector":
        case, cleanup = await _pgvector_case(rows)
    elif backend_name == "chroma":
        case, cleanup = await _chroma_case(rows)
    elif backend_name == "pinecone":
        case, cleanup = await _pinecone_case(rows)
    elif backend_name == "weaviate":
        case, cleanup = await _weaviate_case(rows)
    elif backend_name == "milvus":
        case, cleanup = await _milvus_case(rows)
    else:  # pragma: no cover - argparse choices enforce this
        raise AssertionError(backend_name)

    capabilities = asdict(case.adapter.caps)
    capabilities["ops"] = sorted(capabilities["ops"])
    request.config._vectorsmith_evidence["backends"][backend_name] = {  # type: ignore[attr-defined]
        **case.versions,
        "capabilities": capabilities,
        "capability_proofs": {},
        "results": {
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "duration_seconds": 0.0,
            "failures": [],
        },
    }
    try:
        yield case
    finally:
        await case.adapter.aclose()
        if not os.getenv("VECTORSMITH_KEEP_CONFORMANCE_DATA"):
            await cleanup()


@pytest_asyncio.fixture(loop_scope="session")
async def pgvector_table_case(
    backend_case: BackendCase,
) -> AsyncIterator[BackendCase]:
    if backend_case.name != "pgvector":
        pytest.skip("pgvector table-mode contract")
    dsn = "postgresql://vectorsmith:vectorsmith@localhost:5432/vectorsmith"
    spec = PgvectorConn(
        backend="pgvector",
        dsn=dsn,
        table=backend_case.collection,
        mode="table",
        vector_column=None,
        id_column="id",
    )
    adapter = PgvectorAdapter(spec, {"dsn": dsn})
    try:
        yield BackendCase(
            "pgvector",
            backend_case.collection,
            adapter,
            backend_case.rows,
            backend_case.versions,
        )
    finally:
        await adapter.aclose()


@pytest_asyncio.fixture(loop_scope="session")
async def weaviate_server_embedding_case(
    backend_case: BackendCase,
) -> AsyncIterator[BackendCase]:
    if backend_case.name != "weaviate":
        pytest.skip("Weaviate server-embedding contract")
    import weaviate
    from weaviate.classes.config import Configure, DataType, Property
    from weaviate.classes.data import DataObject

    client = await _retry(lambda: weaviate.connect_to_local())
    if client.collections.exists(SERVER_EMBED_COLLECTION):
        client.collections.delete(SERVER_EMBED_COLLECTION)
    collection = client.collections.create(
        SERVER_EMBED_COLLECTION,
        **_weaviate_vector_create_kwargs(Configure, server=True),
        properties=[
            Property(name="invoice_id", data_type=DataType.TEXT),
            Property(name="body", data_type=DataType.TEXT),
            Property(name="tenant", data_type=DataType.TEXT),
        ],
    )
    seed = backend_case.rows[:50]
    collection.data.insert_many(
        [
            DataObject(
                uuid=row["_id"],
                properties={
                    "invoice_id": row["invoice_id"],
                    "body": row["body"],
                    "tenant": row["tenant"],
                },
            )
            for row in seed
        ]
    )
    adapter = WeaviateAdapter(
        {
            "url": "http://localhost:8080",
            "embedding_mode": "server",
        }
    )
    try:
        yield BackendCase(
            "weaviate",
            SERVER_EMBED_COLLECTION,
            adapter,
            seed,
            backend_case.versions,
        )
    finally:
        await adapter.aclose()
        try:
            client.collections.delete(SERVER_EMBED_COLLECTION)
        finally:
            client.close()


async def _qdrant_case(
    rows: list[dict[str, Any]],
) -> tuple[BackendCase, Callable[[], Any]]:
    from fastembed import SparseTextEmbedding
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.http import models as qm

    client_kwargs: dict[str, Any] = {"url": "http://localhost:6333"}
    if "check_compatibility" in inspect.signature(AsyncQdrantClient).parameters:
        client_kwargs["check_compatibility"] = False
    client = AsyncQdrantClient(**client_kwargs)
    await _retry(client.get_collections)
    if await client.collection_exists(COLLECTION):
        await client.delete_collection(COLLECTION)
    await client.create_collection(
        COLLECTION,
        vectors_config=qm.VectorParams(size=8, distance=qm.Distance.COSINE),
        sparse_vectors_config={"text": qm.SparseVectorParams()},
    )
    await client.create_payload_index(
        COLLECTION,
        field_name="body",
        field_schema=qm.PayloadSchemaType.TEXT,
        wait=True,
    )
    sparse_model = SparseTextEmbedding("Qdrant/bm25")
    sparse_vectors = list(sparse_model.embed([str(row["body"]) for row in rows]))
    for start in range(0, len(rows), 100):
        await client.upsert(
            COLLECTION,
            points=[
                qm.PointStruct(
                    id=row["_id"],
                    vector={
                        "": row["_embedding"],
                        "text": qm.SparseVector(
                            indices=[int(value) for value in sparse.indices],
                            values=[float(value) for value in sparse.values],
                        ),
                    },
                    payload=payload_for(row),
                )
                for row, sparse in zip(
                    rows[start : start + 100],
                    sparse_vectors[start : start + 100],
                    strict=True,
                )
            ],
            wait=True,
        )
    info = await client.get_collection(COLLECTION)
    adapter = QdrantAdapter("http://localhost:6333")

    async def cleanup() -> None:
        try:
            await client.delete_collection(COLLECTION)
        finally:
            await client.close()

    return (
        BackendCase(
            "qdrant",
            COLLECTION,
            adapter,
            rows,
            {
                "client": version("qdrant-client"),
                "server": str(getattr(info, "version", "1.13.2")),
            },
        ),
        cleanup,
    )


async def _chroma_case(
    rows: list[dict[str, Any]],
) -> tuple[BackendCase, Callable[[], Any]]:
    import chromadb

    client = await _retry(
        lambda: chromadb.AsyncHttpClient(host="localhost", port=8000)
    )
    existing = await client.list_collections()
    if COLLECTION in {str(getattr(item, "name", item)) for item in existing}:
        await client.delete_collection(COLLECTION)
    collection = await client.create_collection(COLLECTION)
    for start in range(0, len(rows), 100):
        chunk = rows[start : start + 100]
        await collection.add(
            ids=[row["_id"] for row in chunk],
            embeddings=[row["_embedding"] for row in chunk],
            metadatas=[
                payload_for(row, arrays=False, nested=False, nulls=False)
                for row in chunk
            ],
            documents=[row["body"] for row in chunk],
        )
    adapter = ChromaAdapter("http://localhost:8000")

    async def cleanup() -> None:
        try:
            await client.delete_collection(COLLECTION)
        finally:
            close = getattr(client, "close", None)
            if close:
                result = close()
                if asyncio.iscoroutine(result):
                    await result

    return (
        BackendCase(
            "chroma",
            COLLECTION,
            adapter,
            rows,
            {"client": str(chromadb.__version__), "server": "1.5.0"},
        ),
        cleanup,
    )


async def _pgvector_case(
    rows: list[dict[str, Any]],
) -> tuple[BackendCase, Callable[[], Any]]:
    import psycopg
    from psycopg.types.json import Jsonb

    dsn = "postgresql://vectorsmith:vectorsmith@localhost:5432/vectorsmith"
    table = COLLECTION.lower()

    async def seed() -> None:
        async with await psycopg.AsyncConnection.connect(dsn) as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.execute(f'DROP TABLE IF EXISTS "{table}"')  # noqa: S608
            await conn.execute(
                f'CREATE TABLE "{table}" ('  # noqa: S608
                "id text PRIMARY KEY, payload jsonb NOT NULL, embedding vector(8) NOT NULL)"
            )
            async with conn.cursor() as cursor:
                await cursor.executemany(
                    f'INSERT INTO "{table}" (id, payload, embedding) VALUES (%s, %s, %s)',  # noqa: S608
                    [
                        (row["_id"], Jsonb(payload_for(row)), row["_embedding"])
                        for row in rows
                    ],
                )

    await _retry(seed)
    spec = PgvectorConn(
        backend="pgvector",
        dsn=dsn,
        table=table,
        vector_column="embedding",
        id_column="id",
    )
    adapter = PgvectorAdapter(spec, {"dsn": dsn})

    async def cleanup() -> None:
        async with await psycopg.AsyncConnection.connect(dsn) as conn:
            await conn.execute(f'DROP TABLE IF EXISTS "{table}"')  # noqa: S608

    return (
        BackendCase(
            "pgvector",
            table,
            adapter,
            rows,
            {"client": str(psycopg.__version__), "server": "pgvector/pg16"},
        ),
        cleanup,
    )


async def _weaviate_case(
    rows: list[dict[str, Any]],
) -> tuple[BackendCase, Callable[[], Any]]:
    import weaviate
    from weaviate.classes.config import Configure, DataType, Property
    from weaviate.classes.data import DataObject

    client = await _retry(lambda: weaviate.connect_to_local())
    if client.collections.exists(COLLECTION):
        client.collections.delete(COLLECTION)
    collection = client.collections.create(
        COLLECTION,
        **_weaviate_vector_create_kwargs(Configure, server=False),
        properties=[
            Property(name="invoice_id", data_type=DataType.TEXT),
            Property(name="client_name", data_type=DataType.TEXT),
            Property(name="status", data_type=DataType.TEXT),
            Property(name="due_date", data_type=DataType.TEXT),
            Property(name="amount", data_type=DataType.NUMBER),
            Property(name="sequence", data_type=DataType.INT),
            Property(name="rare_flag", data_type=DataType.BOOL),
            Property(name="tenant", data_type=DataType.TEXT),
            Property(name="body", data_type=DataType.TEXT),
            Property(name="tags", data_type=DataType.TEXT_ARRAY),
            Property(name="labels", data_type=DataType.TEXT_ARRAY),
            Property(name="nullable_note", data_type=DataType.TEXT),
            Property(name="content", data_type=DataType.TEXT),
        ],
    )
    for start in range(0, len(rows), 100):
        collection.data.insert_many(
            [
                DataObject(
                    uuid=row["_id"],
                    properties={
                        **payload_for(row, nested=False, nulls=False),
                        "nullable_note": str(row.get("nullable_note") or ""),
                        "content": str(row.get("content") or ""),
                    },
                    vector=row["_embedding"],
                )
                for row in rows[start : start + 100]
            ]
        )
    adapter = WeaviateAdapter({"url": "http://localhost:8080"})

    async def cleanup() -> None:
        try:
            client.collections.delete(COLLECTION)
        finally:
            client.close()

    return (
        BackendCase(
            "weaviate",
            COLLECTION,
            adapter,
            rows,
            {"client": str(weaviate.__version__), "server": "1.28.5"},
        ),
        cleanup,
    )


async def _milvus_case(
    rows: list[dict[str, Any]],
) -> tuple[BackendCase, Callable[[], Any]]:
    import pymilvus
    from pymilvus import DataType, MilvusClient

    client = await _retry(lambda: MilvusClient(uri="http://localhost:19530"))
    if client.has_collection(COLLECTION):
        client.drop_collection(COLLECTION)
    schema = client.create_schema(auto_id=False, enable_dynamic_field=True)
    schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
    schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=8)
    index = client.prepare_index_params()
    index.add_index(
        field_name="embedding",
        index_type="FLAT",
        metric_type="COSINE",
    )
    client.create_collection(COLLECTION, schema=schema, index_params=index)
    for start in range(0, len(rows), 100):
        client.insert(
            COLLECTION,
            data=[
                {
                    "id": row["_id"],
                    "embedding": row["_embedding"],
                    **payload_for(row, nulls=False),
                }
                for row in rows[start : start + 100]
            ],
        )
    client.flush(COLLECTION)
    adapter = MilvusAdapter({"uri": "http://localhost:19530"})

    async def cleanup() -> None:
        try:
            await asyncio.to_thread(client.drop_collection, COLLECTION)
        finally:
            await asyncio.to_thread(client.close)

    return (
        BackendCase(
            "milvus",
            COLLECTION,
            adapter,
            rows,
            {"client": str(pymilvus.__version__), "server": "2.5.4"},
        ),
        cleanup,
    )


async def _pinecone_case(
    rows: list[dict[str, Any]],
) -> tuple[BackendCase, Callable[[], Any]]:
    import pinecone
    from pinecone import Pinecone, ServerlessSpec

    controller = Pinecone(api_key="pclocal", host="http://localhost:5080")
    index_name = COLLECTION.lower()
    await _retry(controller.list_indexes)
    existing = {item.name for item in controller.list_indexes()}
    if index_name in existing:
        controller.delete_index(index_name)
    controller.create_index(
        name=index_name,
        dimension=8,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-east-1"),
    )
    description = controller.describe_index(index_name)
    host = str(description.host)
    if "://" not in host:
        host = f"http://{host}"
    elif host.startswith("https://localhost"):
        host = "http://" + host.removeprefix("https://")
    index = controller.Index(host=host)
    namespace = "conformance"
    for start in range(0, len(rows), 100):
        index.upsert(
            vectors=[
                {
                    "id": row["_id"],
                    "values": row["_embedding"],
                    "metadata": payload_for(row, nested=False, nulls=False),
                }
                for row in rows[start : start + 100]
            ],
            namespace=namespace,
        )
    adapter = PineconeAdapter(
        {"api_key": "pclocal", "host": host, "namespace": namespace}
    )

    async def cleanup() -> None:
        try:
            await asyncio.to_thread(controller.delete_index, index_name)
        finally:
            index_close = getattr(index, "close", None)
            if callable(index_close):
                await asyncio.to_thread(index_close)
            controller_close = getattr(controller, "close", None)
            if callable(controller_close):
                await asyncio.to_thread(controller_close)

    return (
        BackendCase(
            "pinecone",
            namespace,
            adapter,
            rows,
            {"client": str(pinecone.__version__), "server": "2025-01"},
        ),
        cleanup,
    )
