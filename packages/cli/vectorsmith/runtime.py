"""Compile tools.yaml in-process. Framework adapters wrap this; MCP hosts use ``serve``."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from vectorsmith.context import fresh_call_context
from vectorsmith_core.api import CallContext, load_project
from vectorsmith_core.execute.engine import Engine
from vectorsmith_core.security.credentials import build_credential_resolver


def _read_env_file(path: Path | None) -> dict[str, str]:
    if path is None or not path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def _merge_env(
    env: Mapping[str, str] | None,
    env_file: str | Path | None,
) -> dict[str, str]:
    merged = dict(os.environ)
    if env:
        merged.update(env)
    merged.update(_read_env_file(Path(env_file) if env_file else None))
    return merged


def _one_engine(source: str | Path | dict[str, Any], env: Mapping[str, str]) -> Engine:
    project = load_project(source, env=env)
    errors = [i for i in project.issues if i.severity == "error"]
    if errors:
        msgs = "; ".join(f"{i.code} {i.message}" for i in errors)
        raise ValueError(f"tools.yaml failed validation: {msgs}")
    from vectorsmith_core.security.hardening import serve_hardening_errors

    hard = serve_hardening_errors(project.tds)
    if hard:
        raise ValueError("tools.yaml failed enterprise hardening: " + "; ".join(hard))
    try:
        from vectorsmith_core.embed.provider import FastEmbedProvider

        embed: FastEmbedProvider | None = FastEmbedProvider()
    except Exception:
        embed = None
    from vectorsmith_core.observe.metrics import configure_metrics
    from vectorsmith_core.observe.tracing import configure_tracing

    engine = Engine(
        project,
        credential_resolver=build_credential_resolver(env),
        embed_provider=embed,
    )
    obs = project.tds.observability
    configure_tracing(
        obs.tracing.enabled,
        service_name=obs.tracing.service_name,
        endpoint=obs.tracing.endpoint,
        exporter=obs.tracing.exporter,
    )
    configure_metrics(obs.metrics.enabled)
    return engine


class BoundTools:
    """Compiled YAML tools. Call them directly, or adapt to an agent framework.

    >>> from vectorsmith import connect
    >>> vs = connect("tools.yaml")
    >>> await vs.call("search_invoices", {"query": "Globex", "limit": 3})
    >>> tools = vs.as_langchain()  # pip install 'vectorsmith[langchain]'
    """

    def __init__(self, engines: Sequence[Engine]) -> None:
        self._engines = list(engines)
        self._by_name: dict[str, Engine] = {}
        schemas: list[dict[str, Any]] = []
        for engine in self._engines:
            for schema in engine.project.mcp_tool_schemas():
                name = str(schema["name"])
                self._by_name[name] = engine
                schemas.append(schema)
        self._schemas = schemas

    @property
    def names(self) -> list[str]:
        return [str(s["name"]) for s in self._schemas]

    @property
    def schemas(self) -> list[dict[str, Any]]:
        """MCP tool schemas (``name``, ``description``, ``inputSchema``)."""
        return list(self._schemas)

    def as_anthropic(self) -> list[dict[str, Any]]:
        """Tool defs for ``anthropic.Anthropic().messages.create(tools=...)``."""
        return [
            {
                "name": s["name"],
                "description": s.get("description") or s["name"],
                "input_schema": s.get("inputSchema") or {"type": "object", "properties": {}},
            }
            for s in self._schemas
        ]

    def as_langchain(self) -> Any:
        """LangChain ``StructuredTool`` list. Requires ``vectorsmith[langchain]``."""
        from vectorsmith.langchain_tools import toolset_from_bound

        return toolset_from_bound(self)

    def as_openai_agents(self) -> Any:
        """OpenAI Agents SDK ``FunctionTool`` list. Requires ``vectorsmith[openai-agents]``."""
        from vectorsmith.openai_agents import toolset_from_bound

        return toolset_from_bound(self)

    async def call(
        self,
        name: str,
        args: Mapping[str, Any] | None = None,
        *,
        ctx: CallContext | None = None,
    ) -> dict[str, Any]:
        engine = self._by_name.get(name)
        if engine is None:
            known = ", ".join(self.names) or "(none)"
            raise KeyError(f"unknown tool {name!r}; loaded: {known}")
        clean = {k: v for k, v in dict(args or {}).items() if v is not None}
        result = await engine.call(name, clean, ctx=ctx or fresh_call_context())
        return result.model_dump()

    async def aclose(self) -> None:
        for engine in self._engines:
            await engine.aclose()


def connect(
    *sources: str | Path | dict[str, Any],
    env: Mapping[str, str] | None = None,
    env_file: str | Path | None = None,
) -> BoundTools:
    """Compile one or more tools.yaml files. No MCP subprocess.

    Use this when you want ``await vs.call(...)`` or a non-LangChain adapter.
    LangChain / LangGraph apps can keep using ``load_tools``.
    """
    if not sources:
        raise ValueError("connect requires at least one tools.yaml path")
    merged = _merge_env(env, env_file)
    return BoundTools([_one_engine(source, merged) for source in sources])
