"""Shared 1000-doc conformance dataset (seed=42)."""

from __future__ import annotations

import math
import random
import uuid
from datetime import date, timedelta
from typing import Any

N = 1000
SEED = 42

CLIENTS = [
    "Globex",
    "Initech",
    "Umbrella",
    "Müller GmbH",
    "山田商事",
    "O'Brien & Co",
]


def embedding_for(index: int, dims: int = 8) -> list[float]:
    """Deterministic normalized vector; record 1 is the canonical query vector."""
    raw = [
        math.sin((index + 1) * (axis + 1) * 0.37)
        + math.cos((index + 3) * (axis + 2) * 0.19)
        for axis in range(dims)
    ]
    norm = math.sqrt(sum(value * value for value in raw)) or 1.0
    return [value / norm for value in raw]


def generate_docs(n: int = N, seed: int = SEED) -> list[dict[str, Any]]:
    rng = random.Random(seed)  # noqa: S311 — deterministic fixture, not crypto
    rare = set(rng.sample(range(1, n + 1), max(1, n // 20)))
    docs: list[dict[str, Any]] = []
    for i in range(1, n + 1):
        status = rng.choice(["draft", "sent", "paid", "overdue"])
        row: dict[str, Any] = {
            "_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"vectorsmith-conformance-{i}")),
            "invoice_id": f"INV-{i:04d}",
            "client_name": CLIENTS[(i - 1) % len(CLIENTS)],
            "status": status,
            "due_date": (date(2024, 1, 1) + timedelta(days=rng.randint(0, 800))).isoformat(),
            "amount": round(rng.uniform(100, 20000), 2),
            "sequence": i,
            "rare_flag": i in rare,
            "tenant": "other" if i % 7 == 0 else "acme",
            "body": f"Invoice INV-{i:04d} for {CLIENTS[(i - 1) % len(CLIENTS)]}",
            "tags": ["rare", status] if i in rare else ["standard", status],
            "labels": _labels_for(i, status),
            "profile": {
                "region": ("emea", "amer", "apac")[i % 3],
                "billing": {
                    "tier": ("starter", "growth", "enterprise")[i % 3],
                    "autopay": i % 2 == 0,
                },
            },
            "_embedding": embedding_for(i),
        }
        if i % 10:
            row["nullable_note"] = None if i % 3 == 0 else f"note-{i % 11}"
        if i == 1:
            row["content"] = "metadata-content-must-not-replace-document"
            row["_document"] = "metadata-reserved-key-must-not-win"
        if i == 2:
            row["body"] = "Large conformance document " + ("x" * 20_000)
        docs.append(row)
    return docs


def _labels_for(index: int, status: str) -> list[str]:
    """Deterministic empty, singleton, duplicate, Unicode, and ordinary arrays."""
    if index % 11 == 0:
        return []
    if index % 13 == 0:
        return ["singleton"]
    if index % 17 == 0:
        return ["duplicate", "duplicate"]
    if index % 19 == 0:
        return ["münchen", "東京"]
    return ["finance", status]


def payload_for(
    row: dict[str, Any],
    *,
    arrays: bool = True,
    nested: bool = True,
    nulls: bool = True,
) -> dict[str, Any]:
    """Return a store-safe payload without reserved conformance fields."""
    payload = {
        key: value
        for key, value in row.items()
        if key not in {"_id", "_embedding", "_document"}
    }
    if not arrays:
        payload.pop("tags", None)
        payload.pop("labels", None)
    if not nested:
        payload.pop("profile", None)
    if not nulls:
        payload = {key: value for key, value in payload.items() if value is not None}
    return payload
