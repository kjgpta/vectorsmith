"""Pinecone Local executes every advertised LCD filter during vector search."""

from __future__ import annotations

import pytest

from tests.conformance.conftest import BackendCase
from tests.conformance.oracle import matches, nearest
from vectorsmith_core.adapters.base import SearchRequest
from vectorsmith_core.ir.filter import Cond

pytestmark = [
    pytest.mark.conformance,
    pytest.mark.capability,
    pytest.mark.asyncio(loop_scope="session"),
]


@pytest.mark.parametrize(
    "node",
    [
        Cond("status", "eq", "paid"),
        Cond("status", "ne", "paid"),
        Cond("sequence", "gt", 500),
        Cond("sequence", "gte", 500),
        Cond("sequence", "lt", 500),
        Cond("sequence", "lte", 500),
        Cond("status", "in", ["paid", "sent"]),
        Cond("status", "nin", ["paid", "sent"]),
    ],
)
async def test_pinecone_lcd_vector_filter_matches_oracle(
    backend_case: BackendCase,
    node: Cond,
) -> None:
    if backend_case.name != "pinecone":
        pytest.skip("Pinecone Local contract")
    assert node.op in backend_case.adapter.caps.ops

    query = backend_case.rows[0]["_embedding"]
    expected = nearest(backend_case.rows, query, node)[:10]
    batch = await backend_case.adapter.search(
        SearchRequest(
            collection=backend_case.collection,
            vector=query,
            filter_ir=node,
            limit=10,
            with_score=True,
        )
    )

    assert batch.rows
    assert all(matches(row, node) for row in batch.rows)
    assert [row["_id"] for row in batch.rows] == [row["_id"] for row in expected]
