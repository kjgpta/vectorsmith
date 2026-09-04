"""Deterministic local quality thresholds; never relax to hide adapter defects."""

from __future__ import annotations

import pytest

from tests.conformance.conftest import BackendCase
from vectorsmith_core.adapters.base import SearchRequest
from vectorsmith_core.ir.filter import Cond

pytestmark = [
    pytest.mark.conformance,
    pytest.mark.capability,
    pytest.mark.asyncio(loop_scope="session"),
]

FILTERED_SELF_RECALL_THRESHOLD = 0.98


async def test_filtered_dense_self_recall(backend_case: BackendCase) -> None:
    if not backend_case.adapter.caps.filtered_ann_recall_safe:
        pytest.skip("backend does not advertise safe filtered ANN recall")
    candidates = [
        row
        for row in backend_case.rows
        if row["tenant"] == "acme" and row["rare_flag"]
    ][:20]
    recalled = 0
    for row in candidates:
        result = await backend_case.adapter.search(
            SearchRequest(
                collection=backend_case.collection,
                vector=row["_embedding"],
                filter_ir=Cond("rare_flag", "eq", True),
                limit=1,
            )
        )
        recalled += bool(result.rows and result.rows[0]["_id"] == row["_id"])

    assert candidates
    assert recalled / len(candidates) >= FILTERED_SELF_RECALL_THRESHOLD


async def test_weaviate_hybrid_ranking_has_dense_and_lexical_signal(
    backend_case: BackendCase,
) -> None:
    if backend_case.name != "weaviate":
        pytest.skip("canonical deterministic hybrid fixture currently exists for Weaviate only")
    result = await backend_case.adapter.search(
        SearchRequest(
            collection=backend_case.collection,
            vector=backend_case.rows[0]["_embedding"],
            query_text=str(backend_case.rows[0]["invoice_id"]),
            mode="hybrid",
            alpha=0.5,
            limit=5,
        )
    )

    assert result.rows
    assert result.rows[0]["_id"] == backend_case.rows[0]["_id"]
    assert all("_score" in row for row in result.rows)


async def test_qdrant_hybrid_sparse_ranking_and_ef(
    backend_case: BackendCase,
) -> None:
    if backend_case.name != "qdrant":
        pytest.skip("Qdrant sparse-vector contract")
    result = await backend_case.adapter.search(
        SearchRequest(
            collection=backend_case.collection,
            vector=backend_case.rows[0]["_embedding"],
            query_text=str(backend_case.rows[0]["invoice_id"]),
            mode="hybrid",
            search_ef=64,
            limit=5,
        )
    )

    assert result.rows
    assert result.rows[0]["_id"] == backend_case.rows[0]["_id"]
    assert all("_score" in row for row in result.rows)
