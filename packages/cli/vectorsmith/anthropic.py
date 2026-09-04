"""Anthropic Messages API tools from a tools.yaml.

    pip install "vectorsmith[qdrant]" anthropic
    from vectorsmith.anthropic import load_tools
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from vectorsmith.runtime import BoundTools, connect
from vectorsmith_core.api import CallContext


class AnthropicToolset:
    """``tools`` for ``messages.create``, plus ``execute`` for ``tool_use`` blocks."""

    def __init__(self, bound: BoundTools) -> None:
        self._bound = bound
        self.tools = bound.as_anthropic()

    @property
    def names(self) -> list[str]:
        return self._bound.names

    async def execute(
        self,
        name: str,
        tool_input: Mapping[str, Any] | None = None,
        *,
        ctx: CallContext | None = None,
    ) -> str:
        result = await self._bound.call(name, tool_input, ctx=ctx)
        return json.dumps(result)

    async def aclose(self) -> None:
        await self._bound.aclose()


def load_tools(
    *sources: str | Path | dict[str, Any],
    env: Mapping[str, str] | None = None,
    env_file: str | Path | None = None,
) -> AnthropicToolset:
    """Compile tools.yaml into Anthropic tool defs + an in-process dispatcher."""
    return AnthropicToolset(connect(*sources, env=env, env_file=env_file))
