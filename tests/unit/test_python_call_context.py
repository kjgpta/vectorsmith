from __future__ import annotations

from typing import Any

from vectorsmith.context import coerce_call_context
from vectorsmith.runtime import BoundTools
from vectorsmith_core.api import CallContext, EnvCredentialResolver, ToolResult, load_project
from vectorsmith_core.execute.engine import Engine


def _bound() -> tuple[BoundTools, Engine]:
    project = load_project(
        {
            "tds_version": "2",
            "connections": {
                "main": {"backend": "qdrant", "url": "http://localhost:6333"}
            },
            "tools": [
                {
                    "name": "count_docs",
                    "description": "Count documents under the caller identity and tenant.",
                    "kind": "count",
                    "target": {"connection": "main", "collection": "docs"},
                }
            ],
        },
        env={},
    )
    engine = Engine(project, credential_resolver=EnvCredentialResolver({}))
    return BoundTools([engine]), engine


async def test_bound_tools_propagates_explicit_call_context() -> None:
    bound, engine = _bound()
    seen: list[CallContext] = []

    async def call(
        name: str,
        args: dict[str, Any],
        *,
        ctx: CallContext,
    ) -> ToolResult:
        _ = name, args
        seen.append(ctx)
        return ToolResult(rows=[{"count": 1}], count=1)

    engine.call = call  # type: ignore[method-assign]
    context = CallContext(
        request_id="explicit",
        principal="alice",
        claims={"roles": ["viewer"], "tenant_id": "acme"},
    )

    await bound.call("count_docs", {}, ctx=context)

    assert seen == [context]


def test_framework_context_mapping_preserves_identity_fields() -> None:
    context = coerce_call_context(
        {
            "request_id": "framework",
            "principal": "alice",
            "roles": ["viewer"],
            "claims": {"tenant_id": "acme"},
            "tenant_value": "acme",
        }
    )

    assert context is not None
    assert context.request_id == "framework"
    assert context.principal == "alice"
    assert context.claims == {"tenant_id": "acme", "roles": ["viewer"]}
    assert context.tenant_value == "acme"


async def test_langchain_runnable_config_propagates_call_context() -> None:
    bound, engine = _bound()
    seen: list[CallContext] = []

    async def call(
        name: str,
        args: dict[str, Any],
        *,
        ctx: CallContext,
    ) -> ToolResult:
        _ = name, args
        seen.append(ctx)
        return ToolResult(rows=[{"count": 1}], count=1)

    engine.call = call  # type: ignore[method-assign]
    tool = bound.as_langchain()[0]
    context = CallContext(request_id="langchain", principal="alice")

    await tool.ainvoke(
        {},
        config={"configurable": {"vectorsmith_context": context}},
    )

    assert seen == [context]
