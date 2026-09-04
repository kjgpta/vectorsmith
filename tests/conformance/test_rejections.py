"""Unadvertised filter semantics must fail before backend I/O."""

from __future__ import annotations

import pytest

from tests.conformance.conftest import BackendCase
from vectorsmith_core.errors import InvalidArgumentsError
from vectorsmith_core.ir.filter import Cond

pytestmark = [
    pytest.mark.conformance,
    pytest.mark.capability,
    pytest.mark.asyncio(loop_scope="session"),
]


@pytest.mark.parametrize("operator", ["contains_any", "contains_all"])
async def test_unadvertised_array_operator_is_rejected(
    backend_case: BackendCase,
    operator: str,
) -> None:
    if operator in backend_case.adapter.caps.ops:
        pytest.skip(f"{operator} is advertised")

    with pytest.raises(InvalidArgumentsError, match="does not support"):
        backend_case.adapter.compile_filter(Cond("labels", operator, ["finance"]))


async def test_unadvertised_nested_path_is_rejected(
    backend_case: BackendCase,
) -> None:
    if backend_case.adapter.caps.nested_paths:
        pytest.skip("nested paths are advertised")

    with pytest.raises(InvalidArgumentsError, match="nested"):
        backend_case.adapter.compile_filter(Cond("profile.region", "eq", "emea"))


@pytest.mark.parametrize("operator", ["exists", "is_null"])
async def test_unadvertised_null_operator_is_rejected(
    backend_case: BackendCase,
    operator: str,
) -> None:
    if operator in backend_case.adapter.caps.ops:
        pytest.skip(f"{operator} is advertised")

    with pytest.raises(InvalidArgumentsError, match="does not support"):
        backend_case.adapter.compile_filter(Cond("nullable_note", operator, True))
