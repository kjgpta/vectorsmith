"""Internal executor used by ``vectorsmith serve`` / ``test`` / ``validate --live``.

Application and agent code must not construct this. Consume tools over MCP.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from vectorsmith_core.errors import InvalidArgumentsError, QueryTimeout, RateLimited
from vectorsmith_core.execute.single_step import execute_single
from vectorsmith_core.observe.metrics import inc_rate_limit, inc_tool_call, observe_latency
from vectorsmith_core.observe.tracing import start_span
from vectorsmith_core.security.rate_limit import (
    RateLimiter,
    build_rate_limiter,
    enforce_rate_limits,
)
from vectorsmith_core.security.rbac import check_rbac
from vectorsmith_core.security.tenancy import bind_tenancy, enforce_tenancy, require_tenancy
from vectorsmith_core.tds.models import ChromaConn, PgvectorConn, QdrantConn

if TYPE_CHECKING:
    from vectorsmith_core.api import (
        CallContext,
        CredentialResolver,
        EmbedProvider,
        HealthStatus,
        Issue,
        Project,
        ToolResult,
    )


class Engine:
    """Internal: execute compiled tools against configured backends.

    Not a public SDK. Agents attach ``vectorsmith serve`` as an MCP client.
    """

    def __init__(
        self,
        project: Project,
        *,
        credential_resolver: CredentialResolver,
        embed_provider: EmbedProvider | None = None,
        audit_sink: Any | None = None,
    ) -> None:
        self.project = project
        self.resolver = credential_resolver
        self.embed = embed_provider
        self.audit_sink = audit_sink
        self.rate_limiter: RateLimiter | None = None
        self._adapters: dict[str, Any] = {}

    async def _adapter(self, connection: str) -> Any:
        if connection in self._adapters:
            return self._adapters[connection]
        spec = self.project.tds.connections[connection]
        creds = await self.resolver.resolve(connection, spec)
        adapter = await _build_adapter(spec, creds.values)
        self._adapters[connection] = adapter
        return adapter

    def _embed_for(self, plan: Any) -> Any:
        spec = getattr(plan, "embed_spec", None)
        name = spec.provider if spec is not None else "fastembed"
        if name == "fastembed" and self.embed is not None:
            return self.embed
        from vectorsmith_core.embed.registry import resolve_provider

        return resolve_provider(name)

    async def embed_health(self) -> tuple[bool, str | None]:
        spec = self.project.tds.defaults.embedding
        from vectorsmith_core.embed.registry import resolve_provider

        if spec.provider == "fastembed" and self.embed is not None:
            provider = self.embed
        else:
            provider = resolve_provider(spec.provider)
        check = getattr(provider, "health", None)
        if check is None:
            return True, spec.provider
        try:
            ok = await check()
        except Exception:  # noqa: BLE001
            return False, spec.provider
        return bool(ok), spec.provider

    async def call(
        self,
        tool: str,
        args: dict[str, Any],
        *,
        ctx: CallContext,
        debug: bool = False,
    ) -> ToolResult:
        compiled = self.project.tools.get(tool)
        if compiled is None:
            raise InvalidArgumentsError(
                detail=f"unknown tool '{tool}'; call list_available_tools for the live catalog"
            )
        plan = compiled.plan
        if plan is None:
            raise InvalidArgumentsError(detail=f"tool '{tool}' has no plan")
        if plan.connection is None:
            raise InvalidArgumentsError(detail=f"tool '{tool}' has no connection")
        args = dict(args)
        check_rbac(ctx, tool, self.project.tds.security.rbac)
        try:
            await self._rate_check(ctx, tool)
            if plan.query_param and args.get(plan.query_param):
                await self._rate_check(ctx, tool, embed=True)
                expand = getattr(plan, "expand", None)
                if expand is not None and getattr(expand, "enabled", False):
                    await self._rate_check(ctx, tool, llm=True)
        except RateLimited:
            inc_rate_limit(tool)
            raise
        tenancy = self.project.tds.security.tenancy
        bind_tenancy(tenancy, ctx)
        require_tenancy(tenancy, ctx)
        tenancy_warnings = enforce_tenancy(tenancy, compiled, args, ctx)
        adapter = await self._adapter(plan.connection)
        started = time.perf_counter()
        embed = self._embed_for(plan)
        try:
            async with asyncio.timeout(ctx.deadline_s):
                with start_span(
                    "vectorsmith.tool.call",
                    tool=tool,
                    principal=ctx.principal,
                    connection=plan.connection,
                    collection=str(plan.collection) if plan.collection else None,
                ):
                    if plan.kind == "pipeline":
                        from vectorsmith_core.execute.pipeline import execute_pipeline

                        result = await execute_pipeline(
                            compiled,
                            plan,
                            args,
                            adapter=adapter,
                            embed=embed,
                            ctx=ctx,
                            debug=debug,
                        )
                    else:
                        result = await execute_single(
                            compiled,
                            plan,
                            args,
                            adapter=adapter,
                            embed=embed,
                            ctx=ctx,
                            debug=debug,
                        )
        except TimeoutError as exc:
            inc_tool_call(tool, "timeout")
            raise QueryTimeout(
                detail=f"tool '{tool}' exceeded deadline_s={ctx.deadline_s}"
            ) from exc
        except Exception:
            inc_tool_call(tool, "error")
            raise
        result.latency_ms = int((time.perf_counter() - started) * 1000)
        inc_tool_call(tool, "ok")
        observe_latency(tool, result.latency_ms / 1000)
        if tenancy_warnings:
            result.warnings.extend(tenancy_warnings)
        return result

    async def _rate_check(
        self, ctx: CallContext, tool: str, *, embed: bool = False, llm: bool = False
    ) -> None:
        cfg = self.project.tds.security.rate_limit
        if not cfg.enabled:
            return
        if self.rate_limiter is None:
            self.rate_limiter = build_rate_limiter(cfg)
        if self.rate_limiter is None:
            return
        await enforce_rate_limits(
            self.rate_limiter, cfg, ctx, tool, embed=embed, llm=llm
        )

    async def health(self) -> dict[str, HealthStatus]:
        from vectorsmith_core.api import HealthStatus

        out: dict[str, HealthStatus] = {}
        for name in self.project.tds.connections:
            started = time.perf_counter()
            try:
                adapter = await self._adapter(name)
                ok = await adapter.health()
                ms = int((time.perf_counter() - started) * 1000)
                out[name] = HealthStatus(
                    ok=ok, detail="ok" if ok else "unhealthy", latency_ms=ms
                )
            except Exception as exc:  # noqa: BLE001 — mapped at boundary
                ms = int((time.perf_counter() - started) * 1000)
                out[name] = HealthStatus(ok=False, detail=str(exc), latency_ms=ms)
        return out

    async def introspect(
        self,
        connection: str,
        collections: list[str] | None = None,
        sample_n: int = 200,
        redact_examples: bool = False,
    ) -> dict[str, Any]:
        from vectorsmith_core.introspect.sampling import infer_fields
        from vectorsmith_core.introspect.schema_export import to_schema_json
        from vectorsmith_core.introspect.types import merge_fields

        adapter = await self._adapter(connection)
        names = collections or await adapter.list_collections()
        cols = []
        for c in names:
            native = await adapter.introspect_native(c)
            sample = await adapter.sample(c, sample_n)
            sampled_fields = infer_fields(sample, redact_examples=redact_examples)
            native_fields = (native or {}).get("fields")
            fields = merge_fields(
                list(native_fields) if isinstance(native_fields, list) else [],
                sampled_fields,
            )
            cols.append(
                {
                    "name": c,
                    "native": native,
                    "sampled_n": len(sample),
                    "fields": fields,
                    "introspection": adapter.caps.introspection,
                    "vector": {
                        "sparse": bool((native or {}).get("sparse")),
                        "dim": (native or {}).get("dim"),
                    },
                }
            )
        report = {
            "connection": connection,
            "backend": self.project.tds.connections[connection].backend,
            "collections": cols,
            "redacted": redact_examples,
        }
        return to_schema_json(report)

    async def validate_live(self, *, live_embed: bool = False) -> list[Issue]:
        from vectorsmith_core.api import Issue
        from vectorsmith_core.compilepkg.validator import live_contract_issues, validate
        from vectorsmith_core.introspect.sampling import infer_fields
        from vectorsmith_core.introspect.types import merge_fields

        sparse: dict[str, bool] = {}
        native_map: dict[str, dict[str, Any]] = {}
        extra: list[Issue] = []
        for name in self.project.tds.connections:
            try:
                adapter = await self._adapter(name)
                ok = await adapter.health()
                if not ok:
                    extra.append(
                        Issue(
                            severity="error",
                            code="VB4003",
                            message=f"connection '{name}' is unhealthy",
                            path=name,
                        )
                    )
                collections = await adapter.list_collections()
                for coll in collections:
                    info = dict((await adapter.introspect_native(coll)) or {})
                    try:
                        sample = await adapter.sample(coll, 50)
                        sampled_fields = infer_fields(sample)
                        native_fields = info.get("fields")
                        info["fields"] = merge_fields(
                            list(native_fields) if isinstance(native_fields, list) else [],
                            sampled_fields,
                        )
                    except Exception:  # noqa: BLE001 — sample is best-effort
                        info.setdefault("fields", None)
                    native_map[f"{name}:{coll}"] = info
                    sparse[f"{name}:{coll}"] = bool(info.get("sparse"))
            except Exception as exc:  # noqa: BLE001
                extra.append(
                    Issue(
                        severity="error",
                        code="backend_unreachable",
                        message=str(exc),
                        path=name,
                    )
                )
        extra.extend(validate(self.project.tds, live_sparse=sparse))
        plans = {n: t.plan for n, t in self.project.tools.items() if t.plan is not None}
        extra.extend(live_contract_issues(self.project.tds, plans, native_map))
        if live_embed:
            extra.extend(await self._live_embed_issues(plans))
        seen = {(i.code, i.tool, i.path, i.message) for i in self.project.issues}
        out = list(self.project.issues)
        for issue in extra:
            key = (issue.code, issue.tool, issue.path, issue.message)
            if key not in seen:
                out.append(issue)
        return out

    async def _live_embed_issues(self, plans: dict[str, Any]) -> list[Issue]:
        from vectorsmith_core.api import Issue
        from vectorsmith_core.embed.models import resolve_dims
        from vectorsmith_core.errors import EmbeddingError

        extra: list[Issue] = []
        seen: set[tuple[str, str]] = set()
        for name, plan in plans.items():
            if plan is None or plan.kind not in {"search", "pipeline"}:
                continue
            if isinstance(plan.collection, str) and plan.collection != "__param__":
                adapter = await self._adapter(plan.connection)
                if await adapter.uses_server_side_embedding(plan.collection):
                    continue
            spec = plan.embed_spec
            if spec is None:
                continue
            key = (spec.provider, spec.model)
            if key in seen:
                continue
            seen.add(key)
            provider = self._embed_for(plan)
            try:
                vecs = await provider.embed(
                    ["vectorsmith live-embed probe"], spec.model, config=spec
                )
                got = len(vecs[0]) if vecs and vecs[0] else 0
                expected = resolve_dims(spec.model, spec)
                if got != expected:
                    extra.append(
                        Issue(
                            severity="error",
                            code="VB2017",
                            message=(
                                f"live embed dim {got} != embedder '{spec.model}' ({expected})"
                            ),
                            tool=name,
                        )
                    )
            except EmbeddingError as exc:
                extra.append(
                    Issue(
                        severity="error",
                        code="embedding_error",
                        message=exc.detail,
                        tool=name,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                extra.append(
                    Issue(
                        severity="error",
                        code="embedding_error",
                        message=str(exc),
                        tool=name,
                    )
                )
        return extra

    async def aclose(self) -> None:
        for a in self._adapters.values():
            close = getattr(a, "aclose", None)
            if close:
                await close()
        self._adapters.clear()

    async def __aenter__(self) -> Engine:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()


async def _build_adapter(spec: object, creds: dict[str, str]) -> Any:
    backend = getattr(spec, "backend", None)
    if not isinstance(backend, str):
        raise InvalidArgumentsError(detail="connection is missing backend")
    if backend == "qdrant":
        from vectorsmith_core.adapters.qdrant import QdrantAdapter

        if not isinstance(spec, QdrantConn):
            raise InvalidArgumentsError(detail="qdrant connection mismatch")
        return QdrantAdapter(url=creds.get("url") or spec.url, api_key=creds.get("api_key"))
    if backend == "pgvector":
        from vectorsmith_core.adapters.pgvector import PgvectorAdapter

        if not isinstance(spec, PgvectorConn):
            raise InvalidArgumentsError(detail="pgvector connection mismatch")
        return PgvectorAdapter(spec, creds)
    if backend == "chroma":
        from vectorsmith_core.adapters.chroma import ChromaAdapter

        if not isinstance(spec, ChromaConn):
            raise InvalidArgumentsError(detail="chroma connection mismatch")
        return ChromaAdapter(url=creds.get("url") or spec.url, auth_token=creds.get("auth_token"))
    if backend == "pinecone":
        from vectorsmith_core.adapters.pinecone import PineconeAdapter

        return PineconeAdapter(creds)
    if backend == "weaviate":
        from vectorsmith_core.adapters.weaviate import WeaviateAdapter

        return WeaviateAdapter(creds)
    if backend == "milvus":
        from vectorsmith_core.adapters.milvus import MilvusAdapter

        return MilvusAdapter(creds)
    raise InvalidArgumentsError(detail=f"unknown backend {backend}")

