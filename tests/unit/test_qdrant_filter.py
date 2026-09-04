"""T14: Qdrant compile_filter snapshots for 13 IR shapes."""

from __future__ import annotations

from vectorsmith_core.adapters.qdrant import QdrantAdapter
from vectorsmith_core.ir.filter import And, Cond, Or

A = QdrantAdapter(url="http://localhost:6333")


def test_thirteen_shapes() -> None:
    cases = [
        Cond("status", "eq", "paid"),
        Cond("status", "ne", "draft"),
        Cond("amount", "gt", 10),
        Cond("amount", "gte", 10),
        Cond("amount", "lt", 10),
        Cond("amount", "lte", 10),
        Cond("status", "in", ["paid", "sent"]),
        Cond("status", "nin", ["draft"]),
        And((Cond("tenant", "eq", "acme"), Cond("status", "eq", "paid"))),
        Or((Cond("status", "eq", "paid"), Cond("status", "eq", "overdue"))),
        And(
            (
                Cond("tenant", "eq", "acme"),
                Or((Cond("status", "eq", "paid"), Cond("status", "eq", "sent"))),
            )
        ),
        Cond("nullable_note", "exists", True),
        Cond("nullable_note", "is_null", True),
    ]
    compiled = [A.compile_filter(c) for c in cases]
    assert len(compiled) == 13
    assert compiled[0] == {"must": [{"key": "status", "match": {"value": "paid"}}]}
    assert "must_not" in compiled[1]
    assert compiled[8]["must"][0]["key"] == "tenant"
    assert compiled[9]["should"]
    assert compiled[11] == {
        "must_not": [{"is_empty": {"key": "nullable_note"}}]
    }
    assert compiled[12]["must"][0]["is_null"]["key"] == "nullable_note"
