"""Native introspection returns the shape promised by capabilities."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from tests.conformance.conftest import BackendCase

pytestmark = [
    pytest.mark.conformance,
    pytest.mark.capability,
    pytest.mark.asyncio(loop_scope="session"),
]


async def test_native_introspection_matches_advertised_contract(
    backend_case: BackendCase,
) -> None:
    level = backend_case.adapter.caps.introspection
    if level == "none":
        pytest.skip("native introspection is not advertised")

    result = await backend_case.adapter.introspect_native(backend_case.collection)

    assert isinstance(result, dict)
    assert isinstance(result.get("fields"), Sequence)
    assert result["fields"]
    if level == "typed":
        assert all(
            isinstance(field, dict) and field.get("path") and field.get("dtype")
            for field in result["fields"]
        )
    if backend_case.adapter.vector_capable and backend_case.name != "weaviate":
        assert isinstance(result.get("dim"), int)
        assert result["dim"] > 0
