"""Live adapter behavior compared with the backend-independent oracle."""

from __future__ import annotations

import pytest

from tests.conformance.conftest import BackendCase
from tests.conformance.oracle import filtered, nearest
from vectorsmith_core.adapters.base import SearchRequest
from vectorsmith_core.errors import BackendUnreachable, InvalidArgumentsError
from vectorsmith_core.ir.filter import And, Cond, Or

pytestmark = [pytest.mark.conformance, pytest.mark.asyncio(loop_scope="session")]


async def test_health_and_collection_visibility(backend_case: BackendCase) -> None:
    assert await backend_case.adapter.health()
    assert backend_case.collection in await backend_case.adapter.list_collections()


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        (Cond("status", "eq", "paid"), lambda row: row["status"] == "paid"),
        (Cond("status", "ne", "paid"), lambda row: row["status"] != "paid"),
        (Cond("amount", "gt", 10_000.0), lambda row: row["amount"] > 10_000.0),
        (Cond("amount", "gte", 10_000.0), lambda row: row["amount"] >= 10_000.0),
        (Cond("sequence", "lt", 50), lambda row: row["sequence"] < 50),
        (Cond("sequence", "lte", 50), lambda row: row["sequence"] <= 50),
        (Cond("status", "in", ["paid", "sent"]), lambda row: row["status"] in {"paid", "sent"}),
        (
            Cond("status", "nin", ["paid", "sent"]),
            lambda row: row["status"] not in {"paid", "sent"},
        ),
    ],
)
async def test_comparison_filter_count_matches_oracle(
    backend_case: BackendCase,
    node: Cond,
    expected: object,
) -> None:
    if not backend_case.adapter.caps.count_with_filter:
        pytest.skip("backend does not advertise filtered count")
    oracle = sum(bool(expected(row)) for row in backend_case.rows)  # type: ignore[operator]
    assert await backend_case.adapter.count(backend_case.collection, node) == oracle


async def test_nested_and_or_count_matches_oracle(backend_case: BackendCase) -> None:
    if not backend_case.adapter.caps.count_with_filter:
        pytest.skip("backend does not advertise filtered count")
    node = And(
        (
            Cond("tenant", "eq", "acme"),
            Or((Cond("status", "eq", "paid"), Cond("rare_flag", "eq", True))),
        )
    )
    assert await backend_case.adapter.count(
        backend_case.collection, node
    ) == len(filtered(backend_case.rows, node))


@pytest.mark.parametrize(
    ("operator", "path", "value"),
    [
        ("exists", "nullable_note", True),
        ("is_null", "nullable_note", True),
        ("like", "client_name", "Müller%"),
        ("text_match", "body", "Invoice"),
    ],
)
async def test_advertised_extended_operator_matches_oracle(
    backend_case: BackendCase,
    operator: str,
    path: str,
    value: object,
) -> None:
    if operator not in backend_case.adapter.caps.ops:
        pytest.skip("operator is not advertised")
    if not backend_case.adapter.caps.count_with_filter:
        pytest.skip("exact filtered count is not advertised")
    node = Cond(path, operator, value)

    assert await backend_case.adapter.count(
        backend_case.collection, node
    ) == len(filtered(backend_case.rows, node))


async def test_hidden_tenant_isolation_for_scroll_and_count(
    backend_case: BackendCase,
) -> None:
    tenant_filter = Cond("tenant", "eq", "acme")
    expected = filtered(backend_case.rows, tenant_filter)
    if backend_case.adapter.caps.count_with_filter:
        assert await backend_case.adapter.count(
            backend_case.collection, tenant_filter
        ) == len(expected)
    if not backend_case.adapter.caps.scroll:
        pytest.skip("backend does not advertise scroll")

    batch = await backend_case.adapter.search(
        SearchRequest(
            collection=backend_case.collection,
            filter_ir=tenant_filter,
            limit=100,
        )
    )
    assert batch.rows
    assert all(row["tenant"] == "acme" for row in batch.rows)


async def test_exact_id_lookup_preserves_residual_tenant_filter(
    backend_case: BackendCase,
) -> None:
    if not backend_case.adapter.caps.id_lookup:
        pytest.skip("backend does not advertise guardrail-preserving ID lookup")
    row = next(item for item in backend_case.rows if item["tenant"] == "acme")
    allowed = And((Cond("id", "eq", row["_id"]), Cond("tenant", "eq", "acme")))
    denied = And((Cond("id", "eq", row["_id"]), Cond("tenant", "eq", "other")))

    allowed_result = await backend_case.adapter.search(
        SearchRequest(collection=backend_case.collection, filter_ir=allowed, limit=1)
    )
    denied_result = await backend_case.adapter.search(
        SearchRequest(collection=backend_case.collection, filter_ir=denied, limit=1)
    )

    assert [item["_id"] for item in allowed_result.rows] == [row["_id"]]
    assert denied_result.rows == []


async def test_scroll_offset_projection_and_exhaustion(backend_case: BackendCase) -> None:
    if not backend_case.adapter.caps.scroll:
        pytest.skip("backend does not advertise scroll")
    node = Cond("tenant", "eq", "acme")
    first = await backend_case.adapter.search(
        SearchRequest(
            collection=backend_case.collection,
            filter_ir=node,
            limit=3,
            projection=["invoice_id", "tenant"],
        )
    )
    second = await backend_case.adapter.search(
        SearchRequest(
            collection=backend_case.collection,
            filter_ir=node,
            limit=3,
            offset=3,
            projection=["invoice_id", "tenant"],
        )
    )

    assert len(first.rows) == len(second.rows) == 3
    assert {row["_id"] for row in first.rows}.isdisjoint(row["_id"] for row in second.rows)
    assert all(set(row) <= {"_id", "invoice_id", "tenant"} for row in first.rows + second.rows)
    assert not first.exhausted


async def test_dense_search_is_filtered_and_higher_score_is_better(
    backend_case: BackendCase,
) -> None:
    tenant_filter = Cond("tenant", "eq", "acme")
    oracle = nearest(backend_case.rows, backend_case.rows[0]["_embedding"], tenant_filter)
    batch = await backend_case.adapter.search(
        SearchRequest(
            collection=backend_case.collection,
            vector=backend_case.rows[0]["_embedding"],
            filter_ir=tenant_filter,
            limit=10,
            projection=["invoice_id", "tenant"],
            with_score=True,
        )
    )

    assert batch.rows[0]["_id"] == oracle[0]["_id"]
    assert all(row["tenant"] == "acme" for row in batch.rows)
    assert all("_score" in row for row in batch.rows)
    assert all(
        batch.rows[index]["_score"] >= batch.rows[index + 1]["_score"]
        for index in range(len(batch.rows) - 1)
    )


async def test_dense_search_can_exclude_score(backend_case: BackendCase) -> None:
    batch = await backend_case.adapter.search(
        SearchRequest(
            collection=backend_case.collection,
            vector=backend_case.rows[0]["_embedding"],
            limit=3,
            with_score=False,
        )
    )
    assert all("_score" not in row for row in batch.rows)


async def test_unicode_and_rare_filter_survive_native_round_trip(
    backend_case: BackendCase,
) -> None:
    node = And((Cond("client_name", "eq", "山田商事"), Cond("rare_flag", "eq", True)))
    if backend_case.adapter.caps.count_with_filter:
        assert await backend_case.adapter.count(
            backend_case.collection, node
        ) == len(filtered(backend_case.rows, node))
    elif backend_case.adapter.caps.scroll:
        result = await backend_case.adapter.search(
            SearchRequest(collection=backend_case.collection, filter_ir=node, limit=100)
        )
        assert len(result.rows) == len(filtered(backend_case.rows, node))
    else:
        pytest.skip("no exact filter-only contract is advertised")


async def test_unsupported_semantics_fail_explicitly(backend_case: BackendCase) -> None:
    if backend_case.name == "pinecone":
        with pytest.raises(InvalidArgumentsError, match="filter-only"):
            await backend_case.adapter.search(
                SearchRequest(collection=backend_case.collection, limit=1)
            )
        with pytest.raises(InvalidArgumentsError, match="filtered counts"):
            await backend_case.adapter.count(
                backend_case.collection, Cond("tenant", "eq", "acme")
            )


async def test_backend_errors_do_not_leak_foreign_exceptions(
    backend_case: BackendCase,
) -> None:
    original = backend_case.adapter._client if hasattr(backend_case.adapter, "_client") else None
    if not hasattr(backend_case.adapter, "_client"):
        pytest.skip("adapter has no injectable client")

    class Broken:
        def __getattr__(self, name: str) -> object:
            raise RuntimeError(f"foreign failure from {name}")

    backend_case.adapter._client = Broken()  # type: ignore[attr-defined]
    try:
        with pytest.raises((BackendUnreachable, InvalidArgumentsError)):
            await backend_case.adapter.search(
                SearchRequest(
                    collection=backend_case.collection,
                    vector=backend_case.rows[0]["_embedding"],
                    limit=1,
                )
            )
    finally:
        backend_case.adapter._client = original  # type: ignore[attr-defined]
