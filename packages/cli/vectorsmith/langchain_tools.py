"""LangChain / LangGraph tools from a tools.yaml.

Application code: write YAML, then ``from vectorsmith import load_tools``.
Hosts that cannot import Python (Claude Desktop, Codex, Cursor) use
``vectorsmith serve`` instead. Same YAML.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field, create_model

from vectorsmith.context import fresh_call_context
from vectorsmith.runtime import BoundTools, connect
from vectorsmith_core.execute.engine import Engine

_JSON_TO_PY: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
}


class Toolset(list[BaseTool]):
    """LangChain tools plus the engines that back them. Call ``aclose`` when done."""

    def __init__(self, tools: Sequence[BaseTool], engines: Sequence[Engine]) -> None:
        super().__init__(tools)
        self._engines = list(engines)

    async def aclose(self) -> None:
        for engine in self._engines:
            await engine.aclose()


def _py_type(spec: dict[str, Any]) -> type:
    if spec.get("type") == "array":
        item = _JSON_TO_PY.get((spec.get("items") or {}).get("type", "string"), str)
        return list[item]  # type: ignore[valid-type]
    return _JSON_TO_PY.get(str(spec.get("type", "string")), str)


def _args_model(tool_name: str, input_schema: dict[str, Any]) -> type[BaseModel]:
    props = input_schema.get("properties") or {}
    required = set(input_schema.get("required") or [])
    fields: dict[str, Any] = {}
    for key, spec in props.items():
        typ = _py_type(spec if isinstance(spec, dict) else {})
        desc = spec.get("description") if isinstance(spec, dict) else None
        if key in required:
            fields[key] = (typ, Field(..., description=desc))
        else:
            default = spec.get("default") if isinstance(spec, dict) else None
            fields[key] = (typ | None, Field(default, description=desc))
    if not fields:
        return create_model(f"{tool_name}Args")
    return create_model(f"{tool_name}Args", **fields)


def _bind(engine: Engine, name: str, schema: dict[str, Any]) -> StructuredTool:
    async def _arun(
        config: RunnableConfig = None,  # type: ignore[assignment]
        **kwargs: Any,
    ) -> dict[str, Any]:
        clean = {k: v for k, v in kwargs.items() if v is not None}
        result = await engine.call(name, clean, ctx=fresh_call_context(config))
        return result.model_dump()

    def _run(
        config: RunnableConfig = None,  # type: ignore[assignment]
        **kwargs: Any,
    ) -> dict[str, Any]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_arun(config=config, **kwargs))
        raise RuntimeError(f"tool {name!r} must be awaited in an async context")

    return StructuredTool(
        name=name,
        description=schema.get("description") or name,
        args_schema=_args_model(name, schema.get("inputSchema") or {}),
        coroutine=_arun,
        func=_run,
    )


def toolset_from_bound(bound: BoundTools) -> Toolset:
    tools: list[BaseTool] = []
    for engine in bound._engines:
        for schema in engine.project.mcp_tool_schemas():
            tools.append(_bind(engine, str(schema["name"]), schema))
    return Toolset(tools, bound._engines)


def load_tools(
    *sources: str | Path | dict[str, Any],
    env: Mapping[str, str] | None = None,
    env_file: str | Path | None = None,
) -> Toolset:
    """Compile one or more tools.yaml files into LangChain / LangGraph tools.

    >>> from vectorsmith import load_tools
    >>> tools = load_tools("tools.invoices.yaml", "tools.tickets.yaml")
    >>> # pass ``tools`` into create_agent / create_react_agent; await tools.aclose()
    """
    return connect(*sources, env=env, env_file=env_file).as_langchain()
