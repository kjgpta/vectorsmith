"""OpenAI Agents SDK tools from a tools.yaml.

    pip install "vectorsmith[qdrant,openai-agents]"
    from vectorsmith.openai_agents import load_tools
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from vectorsmith.context import coerce_call_context
from vectorsmith.runtime import BoundTools, connect


class OpenAIAgentToolset(list[Any]):
    """FunctionTool list plus ``aclose`` for the backing engines."""

    def __init__(self, tools: Sequence[Any], bound: BoundTools) -> None:
        super().__init__(tools)
        self._bound = bound

    async def aclose(self) -> None:
        await self._bound.aclose()


def _function_tool(bound: BoundTools, schema: dict[str, Any]) -> Any:
    try:
        from agents import FunctionTool
    except ImportError as exc:
        raise ImportError(
            "OpenAI Agents SDK is required. Install with: "
            'pip install "vectorsmith[openai-agents]"'
        ) from exc

    name = str(schema["name"])
    params = schema.get("inputSchema") or {"type": "object", "properties": {}}

    async def _on_invoke(_ctx: Any, raw: str) -> str:
        try:
            args = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            args = {}
        if not isinstance(args, dict):
            return json.dumps({"error": "tool arguments must be a JSON object"})
        result = await bound.call(name, args, ctx=coerce_call_context(_ctx))
        return json.dumps(result)

    return FunctionTool(
        name=name,
        description=schema.get("description") or name,
        params_json_schema=params,
        on_invoke_tool=_on_invoke,
        strict_json_schema=False,
    )


def toolset_from_bound(bound: BoundTools) -> OpenAIAgentToolset:
    return OpenAIAgentToolset([_function_tool(bound, s) for s in bound.schemas], bound)


def load_tools(
    *sources: str | Path | dict[str, Any],
    env: Mapping[str, str] | None = None,
    env_file: str | Path | None = None,
) -> OpenAIAgentToolset:
    """Compile tools.yaml into OpenAI Agents SDK ``FunctionTool``s."""
    return connect(*sources, env=env, env_file=env_file).as_openai_agents()
