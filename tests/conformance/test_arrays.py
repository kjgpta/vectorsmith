"""Array storage and containment semantics are capability-gated."""

from __future__ import annotations

import pytest

from tests.conformance.conftest import BackendCase
from tests.conformance.oracle import filtered, nearest
from vectorsmith_core.adapters.base import SearchRequest
from vectorsmith_core.ir.filter import Cond

pytestmark = [
    pytest.mark.conformance,
    pytest.mark.capability,
    pytest.mark.asyncio(loop_scope="session"),
]


async def test_array_values_survive_round_trip(backend_case: BackendCase) -> None:
    if not backend_case.adapter.caps.arrays:
        pytest.skip("arrays are not advertised")
    if not backend_case.adapter.caps.scroll:
        pytest.skip("filter-only reads are not advertised")

    batch = await backend_case.adapter.search(
        SearchRequest(
            collection=backend_case.collection,
            limit=100,
            projection=["labels"],
            with_score=False,
        )
    )

    assert batch.rows
    assert all(isinstance(row["labels"], list) for row in batch.rows)
    assert any(not row["labels"] for row in batch.rows)


@pytest.mark.parametrize(
    "node",
    [
        Cond("labels", "contains_any", ["東京", "singleton"]),
        Cond("labels", "contains_all", ["finance", "paid"]),
    ],
)
async def test_advertised_array_containment_matches_oracle(
    backend_case: BackendCase,
    node: Cond,
) -> None:
    if not backend_case.adapter.caps.arrays:
        pytest.skip("arrays are not advertised")
    if node.op not in backend_case.adapter.caps.ops:
        pytest.skip(f"{node.op} is not advertised")
    if backend_case.adapter.caps.count_with_filter:
        assert await backend_case.adapter.count(
            backend_case.collection, node
        ) == len(filtered(backend_case.rows, node))
        return

    query = backend_case.rows[0]["_embedding"]
    expected = nearest(backend_case.rows, query, node)[:10]
    batch = await backend_case.adapter.search(
        SearchRequest(
            collection=backend_case.collection,
            vector=query,
            filter_ir=node,
            limit=10,
        )
    )
    assert [row["_id"] for row in batch.rows] == [
        row["_id"] for row in expected
    ]
