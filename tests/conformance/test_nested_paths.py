"""Nested payload paths match the backend-independent oracle."""

from __future__ import annotations

import pytest

from tests.conformance.conftest import BackendCase
from tests.conformance.oracle import filtered
from vectorsmith_core.ir.filter import And, Cond

pytestmark = [
    pytest.mark.conformance,
    pytest.mark.capability,
    pytest.mark.asyncio(loop_scope="session"),
]


@pytest.mark.parametrize(
    "node",
    [
        Cond("profile.region", "eq", "emea"),
        Cond("profile.billing.tier", "eq", "enterprise"),
        And(
            (
                Cond("profile.region", "eq", "amer"),
                Cond("profile.billing.autopay", "eq", True),
            )
        ),
    ],
)
async def test_nested_path_count_matches_oracle(
    backend_case: BackendCase,
    node: Cond | And,
) -> None:
    if not backend_case.adapter.caps.nested_paths:
        pytest.skip("nested paths are not advertised")
    if not backend_case.adapter.caps.count_with_filter:
        pytest.skip("exact filtered count is not advertised")

    assert await backend_case.adapter.count(
        backend_case.collection, node
    ) == len(filtered(backend_case.rows, node))
