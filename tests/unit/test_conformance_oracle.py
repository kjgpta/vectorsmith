from __future__ import annotations

from tests.conformance.dataset import embedding_for, generate_docs, payload_for
from tests.conformance.oracle import filtered, matches, nearest, page
from vectorsmith_core.ir.filter import And, Cond, Or


def test_dataset_is_reproducible_and_contains_edge_cases() -> None:
    first = generate_docs()
    second = generate_docs()

    assert first == second
    assert len(first) == 1000
    assert {row["tenant"] for row in first} == {"acme", "other"}
    assert any("nullable_note" not in row for row in first)
    assert any(row.get("nullable_note", "missing") is None for row in first)
    assert any("Müller" in row["client_name"] for row in first)
    assert any("山田" in row["client_name"] for row in first)
    assert {row["profile"]["region"] for row in first} == {"amer", "apac", "emea"}
    assert any(row["labels"] == [] for row in first)
    assert any(row["labels"] == ["singleton"] for row in first)
    assert any(row["labels"] == ["duplicate", "duplicate"] for row in first)
    assert any(row["labels"] == ["münchen", "東京"] for row in first)


def test_payload_removes_reserved_fields_and_optional_native_values() -> None:
    row = generate_docs(3)[2]

    payload = payload_for(row, arrays=False, nested=False, nulls=False)

    assert "_id" not in payload
    assert "_embedding" not in payload
    assert "_document" not in payload
    assert "tags" not in payload
    assert "labels" not in payload
    assert "profile" not in payload
    assert all(value is not None for value in payload.values())


def test_oracle_evaluates_nested_filters_and_missing_values() -> None:
    row = {"amount": 50, "status": "paid", "nullable": None}
    node = And(
        (
            Cond("amount", "gte", 50),
            Or((Cond("status", "eq", "paid"), Cond("status", "eq", "sent"))),
            Cond("nullable", "is_null", True),
            Cond("absent", "exists", False),
        )
    )

    assert matches(row, node)
    assert matches(row, Cond("absent", "ne", "value"))
    assert matches(row, Cond("absent", "nin", ["value"]))
    assert not matches(row, Cond("absent", "eq", None))
    assert not matches(row, Cond("absent", "is_null", True))
    assert matches(row, Cond("absent", "is_null", False))
    assert matches(row, Cond("absent", "exists", False))
    assert matches(row, Cond("nullable", "is_null", True))
    assert not matches(row, Cond("nullable", "is_null", False))
    assert matches(row, Cond("nullable", "ne", "value"))
    assert matches(row, Cond("nullable", "nin", ["value"]))


def test_oracle_array_containment_is_explicit() -> None:
    row = {"labels": ["finance", "paid", "paid"], "scalar": "finance"}

    assert matches(row, Cond("labels", "contains_any", ["missing", "paid"]))
    assert not matches(row, Cond("labels", "contains_any", ["missing"]))
    assert matches(row, Cond("labels", "contains_all", ["finance", "paid"]))
    assert not matches(row, Cond("labels", "contains_all", ["finance", "missing"]))
    assert not matches(row, Cond("labels", "contains_all", []))
    assert not matches(row, Cond("scalar", "contains_any", ["finance"]))
    assert not matches(row, Cond("absent", "contains_any", ["finance"]))


def test_oracle_filter_count_paging_projection_and_ranking() -> None:
    rows = generate_docs(40)
    tenant_filter = Cond("tenant", "eq", "acme")
    tenant_rows = filtered(rows, tenant_filter)

    ranked = nearest(rows, embedding_for(1), tenant_filter)
    result = page(ranked, limit=3, offset=1, projection=["invoice_id"])

    assert len(tenant_rows) == 35
    assert len(result) == 3
    assert set(result[0]) == {"_id", "_score", "invoice_id"}
    assert all(
        ranked[index]["_score"] >= ranked[index + 1]["_score"]
        for index in range(len(ranked) - 1)
    )
