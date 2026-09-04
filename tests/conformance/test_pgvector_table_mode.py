"""pgvector table mode preserves non-vector lookup and count contracts."""

from __future__ import annotations

import pytest

from tests.conformance.conftest import BackendCase
from tests.conformance.oracle import filtered
from vectorsmith_core.adapters.base import SearchRequest
from vectorsmith_core.errors import InvalidArgumentsError
from vectorsmith_core.ir.filter import Cond

pytestmark = [
    pytest.mark.conformance,
    pytest.mark.capability,
    pytest.mark.asyncio(loop_scope="session"),
]


async def test_table_mode_supports_filtered_count_and_scroll(
    pgvector_table_case: BackendCase,
) -> None:
    case = pgvector_table_case
    node = Cond("tenant", "eq", "acme")

    assert not case.adapter.vector_capable
    assert await case.adapter.count(case.collection, node) == len(filtered(case.rows, node))

    batch = await case.adapter.search(
        SearchRequest(
            collection=case.collection,
            filter_ir=node,
            limit=5,
            projection=["tenant", "invoice_id"],
            with_score=False,
        )
    )
    assert len(batch.rows) == 5
    assert all(row["tenant"] == "acme" for row in batch.rows)


async def test_table_mode_rejects_vector_search(
    pgvector_table_case: BackendCase,
) -> None:
    with pytest.raises(InvalidArgumentsError, match="table mode"):
        await pgvector_table_case.adapter.search(
            SearchRequest(
                collection=pgvector_table_case.collection,
                vector=pgvector_table_case.rows[0]["_embedding"],
            )
        )
