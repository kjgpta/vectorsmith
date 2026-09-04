"""Backend-independent semantic oracle for adapter conformance."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from vectorsmith_core.ir.filter import And, Cond, IRNode, Or

MISSING = object()


def _value(row: Mapping[str, Any], path: str) -> object:
    value: object = row
    for segment in path.split("."):
        if not isinstance(value, Mapping) or segment not in value:
            return MISSING
        value = value[segment]
    return value


def _values(value: object) -> tuple[object, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(value)
    return (value,)


def matches(row: Mapping[str, Any], node: IRNode | None) -> bool:
    if node is None:
        return True
    if isinstance(node, And):
        return all(matches(row, child) for child in node.children)
    if isinstance(node, Or):
        return any(matches(row, child) for child in node.children)
    if not isinstance(node, Cond):
        raise TypeError(f"unsupported filter node: {type(node).__name__}")

    actual = _value(row, node.path)
    expected = node.value
    if node.op == "exists":
        exists = actual is not MISSING and actual is not None
        return exists if expected is not False else not exists
    if node.op == "is_null":
        is_null = actual is None
        return is_null if expected is not False else not is_null
    if actual is MISSING:
        return node.op in {"ne", "nin"}
    if node.op == "eq":
        return actual == expected
    if node.op == "ne":
        return actual != expected
    if node.op == "gt":
        return bool(actual > expected)  # type: ignore[operator]
    if node.op == "gte":
        return bool(actual >= expected)  # type: ignore[operator]
    if node.op == "lt":
        return bool(actual < expected)  # type: ignore[operator]
    if node.op == "lte":
        return bool(actual <= expected)  # type: ignore[operator]
    if node.op == "in":
        return actual in expected
    if node.op == "nin":
        return actual not in expected
    if node.op == "contains_any":
        if not isinstance(actual, Sequence) or isinstance(actual, (str, bytes, bytearray)):
            return False
        return any(value in actual for value in _values(expected))
    if node.op == "contains_all":
        if not isinstance(actual, Sequence) or isinstance(actual, (str, bytes, bytearray)):
            return False
        required = _values(expected)
        return bool(required) and all(value in actual for value in required)
    if node.op in {"like", "text_match"}:
        pattern = re.escape(str(expected)).replace("%", ".*").replace("_", ".")
        return re.search(pattern, str(actual), flags=re.IGNORECASE) is not None
    raise ValueError(f"unsupported filter operator: {node.op}")


def filtered(rows: Iterable[dict[str, Any]], node: IRNode | None) -> list[dict[str, Any]]:
    return [row for row in rows if matches(row, node)]


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def nearest(
    rows: Iterable[dict[str, Any]],
    query: Sequence[float],
    node: IRNode | None = None,
) -> list[dict[str, Any]]:
    ranked = []
    for row in filtered(rows, node):
        candidate = dict(row)
        candidate["_score"] = cosine(query, candidate["_embedding"])
        ranked.append(candidate)
    return sorted(ranked, key=lambda row: (-row["_score"], str(row["_id"])))


def page(
    rows: Sequence[dict[str, Any]],
    *,
    limit: int,
    offset: int | None = None,
    projection: list[str] | None = None,
) -> list[dict[str, Any]]:
    selected = rows[offset or 0 : (offset or 0) + limit]
    if projection is None:
        return [dict(row) for row in selected]
    always = {"_id", "_score"}
    return [
        {key: value for key, value in row.items() if key in always or key in projection}
        for row in selected
    ]
