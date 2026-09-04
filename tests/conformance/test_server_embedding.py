"""Weaviate collection vectorizers execute text queries without client vectors."""

from __future__ import annotations

import pytest

from tests.conformance.conftest import BackendCase
from vectorsmith_core.adapters.base import SearchRequest

pytestmark = [
    pytest.mark.conformance,
    pytest.mark.capability,
    pytest.mark.asyncio(loop_scope="session"),
]


async def test_weaviate_server_side_embedding_search(
    weaviate_server_embedding_case: BackendCase,
) -> None:
    case = weaviate_server_embedding_case
    query_row = case.rows[0]
    assert await case.adapter.uses_server_side_embedding(case.collection)

    batch = await case.adapter.search(
        SearchRequest(
            collection=case.collection,
            vector=None,
            query_text=str(query_row["body"]),
            limit=5,
            with_score=True,
        )
    )

    assert batch.rows
    assert all(row["invoice_id"] for row in batch.rows)
    assert all("_score" in row for row in batch.rows)
