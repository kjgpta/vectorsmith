"""Single-step execution (tech §6 steps 4–13)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal

from vectorsmith_core.adapters.base import SearchRequest
from vectorsmith_core.errors import InvalidArgumentsError
from vectorsmith_core.ir.filter import Cond, bind, invert_cond, merge_and

if TYPE_CHECKING:
    from vectorsmith_core.adapters.base import VectorBackendAdapter
    from vectorsmith_core.api import CallContext, CompiledTool, EmbedProvider, ToolResult
    from vectorsmith_core.compilepkg.compiler import ExecutionPlan

MAX_BYTES = 100_000


def _validate_args(schema: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    import jsonschema

    props = schema.get("inputSchema") or schema
    try:
        jsonschema.validate(args, props if props.get("type") == "object" else schema["inputSchema"])
    except jsonschema.ValidationError as exc:
        raise InvalidArgumentsError(detail=exc.message) from exc
    return args


async def execute_single(
    compiled: CompiledTool,
    plan: ExecutionPlan,
    args: dict[str, Any],
    *,
    adapter: VectorBackendAdapter,
    embed: EmbedProvider | None,
    ctx: CallContext,
    debug: bool = False,
) -> ToolResult:
    from vectorsmith_core.api import ToolResult

    _validate_args(compiled.mcp_schema, args)
    unresolved = await _apply_resolvers(plan, args, adapter)
    if unresolved is not None:
        return unresolved
    required = {
        p
        for p in (compiled.mcp_schema.get("inputSchema") or {}).get("required", [])
    }
    bound_params = bind(
        merge_and(*plan.param_conds) if plan.param_conds else None,
        args,
        required=frozenset(required) - {plan.query_param or ""},
    )
    must = list(plan.static_must or plan.static_conds)
    must_not = [invert_cond(c) for c in (plan.static_must_not or [])]
    tenant = getattr(ctx, "tenant_filter", None) if ctx is not None else None
    ir = merge_and(*must, *must_not, bound_params, tenant)

    native = adapter.compile_filter(ir)
    collection = args.get("collection") if plan.collection == "__param__" else plan.collection
    if not isinstance(collection, str):
        raise InvalidArgumentsError(detail="collection is required")

    warnings: list[str] = []
    search_mode: Literal["dense", "hybrid", "none"] = "none"
    query_text = args.get(plan.query_param) if plan.query_param else None

    if plan.kind == "meta":
        names = await adapter.list_collections()
        rows: list[dict[str, Any]] = []
        for name in names:
            try:
                n = await adapter.count(name, None)
                rows.append({"collection": name, "approx_count": n})
            except Exception:  # noqa: BLE001 — count is best-effort for meta
                rows.append({"collection": name, "approx_count": None})
                warnings.append("VB4003")
        return ToolResult(rows=rows, count=len(rows), search_mode="none", warnings=warnings)

    if plan.kind == "count":
        n = await adapter.count(collection, ir)
        return ToolResult(rows=[{"count": n}], count=n, search_mode="none")

    texts: list[str] = []
    if query_text:
        texts = [str(query_text)]
        expand_spec = plan.expand
        if expand_spec is not None and getattr(expand_spec, "enabled", False):
            from vectorsmith_core.execute.expand import expand_query

            texts, exp_warn = await expand_query(str(query_text), expand_spec)
            if exp_warn:
                warnings.append(exp_warn)
        search_mode = "hybrid" if plan.mode == "hybrid" else "dense"
    elif plan.query_required:
        raise InvalidArgumentsError(detail=f"missing required argument '{plan.query_param}'")

    limit = int(args.get("limit") or plan.limit_default)
    limit = max(1, min(limit, plan.limit_max))
    search_limit = limit
    rerank_spec = plan.rerank
    if rerank_spec is not None and getattr(rerank_spec, "enabled", False):
        search_limit = max(limit, int(getattr(rerank_spec, "retrieve_k", 50)))

    if texts:
        rows = await _search_variants(
            adapter,
            embed,
            plan,
            texts,
            collection=collection,
            ir=ir,
            search_limit=search_limit,
        )
    else:
        from vectorsmith_core.observe.tracing import start_span

        with start_span(
            "vectorsmith.adapter.search",
            backend=getattr(adapter, "backend", None),
            collection=collection,
            limit=search_limit,
            mode=plan.mode,
        ):
            batch = await adapter.search(
                SearchRequest(
                    collection=collection,
                    vector=None,
                    mode="hybrid" if plan.mode == "hybrid" else "dense",
                    query_text=None,
                    alpha=plan.alpha,
                    filter_ir=ir,
                    limit=search_limit,
                    projection=plan.projection,
                    with_score=plan.include_score,
                    min_score=plan.min_score,
                    search_ef=plan.search_ef,
                )
            )
        rows = batch.rows
    if plan.min_score is not None:
        kept = []
        for row in rows:
            score = row.get("_score")
            if score is None or float(score) >= plan.min_score:
                kept.append(row)
        rows = kept
    if query_text and rerank_spec is not None and getattr(rerank_spec, "enabled", False):
        from vectorsmith_core.execute.rerank import rerank_rows

        rows, rw = await rerank_rows(str(query_text), rows, rerank_spec, limit=limit)
        if rw:
            warnings.append(rw)
    else:
        rows = rows[:limit]
    if plan.projection:
        projected = []
        missing = False
        for row in rows:
            item = {k: row.get(k) for k in plan.projection}
            if any(k not in row for k in plan.projection):
                missing = True
            if plan.include_score and "_score" in row:
                item["_score"] = row["_score"]
            if plan.include_id and "_id" in row:
                item.setdefault("_id", row["_id"])
            projected.append(item)
        rows = projected
        if missing:
            warnings.append("VB4001")

    from vectorsmith_core.execute.output import apply_output_policy

    rows = apply_output_policy(rows, plan)

    truncated = False
    encoded = json.dumps(rows, default=str).encode()
    while len(encoded) > MAX_BYTES and rows:
        rows = rows[:-1]
        truncated = True
        encoded = json.dumps(rows, default=str).encode()

    return ToolResult(
        rows=rows,
        count=len(rows),
        truncated=truncated,
        search_mode=search_mode if query_text else "none",
        warnings=warnings,
        compiled_query={"filter": native} if debug else None,
    )


async def _apply_resolvers(
    plan: ExecutionPlan,
    args: dict[str, Any],
    adapter: VectorBackendAdapter,
) -> ToolResult | None:
    from vectorsmith_core.api import ToolResult
    from vectorsmith_core.execute.resolve import resolve_value
    from vectorsmith_core.tds.models import ResolveSpec

    for name, meta in (plan.param_resolve or {}).items():
        if name not in args or args[name] is None:
            continue
        raw_spec = meta.get("resolve") if isinstance(meta, dict) else None
        if not isinstance(raw_spec, ResolveSpec) or raw_spec.kind != "directory":
            continue
        conn = raw_spec.connection or plan.connection
        coll = raw_spec.collection or plan.collection
        if not isinstance(conn, str) or not isinstance(coll, str):
            continue
        enum = meta.get("enum") if isinstance(meta, dict) else []
        result = await resolve_value(
            str(args[name]),
            raw_spec,
            adapter=adapter,
            connection=conn,
            collection=coll,
            enum=list(enum or []),
        )
        if result.value is None:
            return ToolResult(
                rows=[],
                count=0,
                warnings=["VB4020"],
                message=result.error,
                search_mode="none",
            )
        args[name] = result.value
    return None


def _row_key(row: dict[str, Any]) -> str:
    if row.get("_id") is not None:
        return str(row["_id"])
    if row.get("id") is not None:
        return str(row["id"])
    return str(id(row))


async def _embed_one(embed: Any, text: str, plan: Any) -> list[float]:
    from vectorsmith_core.errors import EmbeddingError
    from vectorsmith_core.observe.metrics import inc_embed
    from vectorsmith_core.observe.tracing import start_span

    model = plan.embedding or "fastembed/BAAI/bge-small-en-v1.5"
    provider = getattr(plan.embed_spec, "provider", None) or "fastembed"
    with start_span("vectorsmith.embed", provider=provider, model=model, text_count=1):
        try:
            vectors = await embed.embed([text], model, config=plan.embed_spec)
        except TypeError:
            vectors = await embed.embed([text], model)
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError(detail=str(exc)) from exc
    inc_embed(str(provider))
    return [float(x) for x in vectors[0]]


async def _search_variants(
    adapter: VectorBackendAdapter,
    embed: Any | None,
    plan: Any,
    texts: list[str],
    *,
    collection: str,
    ir: Any,
    search_limit: int,
) -> list[dict[str, Any]]:
    from vectorsmith_core.observe.tracing import start_span

    merged: dict[str, dict[str, Any]] = {}
    server_side_check = getattr(adapter, "uses_server_side_embedding", None)
    server_side = (
        bool(await server_side_check(collection))
        if callable(server_side_check)
        else False
    )
    if not server_side and embed is None:
        raise InvalidArgumentsError(detail="query provided but no embed provider configured")
    for text in texts:
        vector = None if server_side else await _embed_one(embed, text, plan)
        with start_span(
            "vectorsmith.adapter.search",
            backend=getattr(adapter, "name", None) or getattr(adapter, "backend", None),
            collection=collection,
            limit=search_limit,
            mode=plan.mode,
        ):
            batch = await adapter.search(
                SearchRequest(
                    collection=collection,
                    vector=vector,
                    mode="hybrid" if plan.mode == "hybrid" else "dense",
                    query_text=text,
                    alpha=plan.alpha,
                    filter_ir=ir,
                    limit=search_limit,
                    projection=plan.projection,
                    with_score=plan.include_score,
                    min_score=plan.min_score,
                    search_ef=plan.search_ef,
                )
            )
        for row in batch.rows:
            key = _row_key(row)
            prev = merged.get(key)
            if prev is None or float(row.get("_score") or 0) > float(prev.get("_score") or 0):
                merged[key] = row
    rows = list(merged.values())
    rows.sort(key=lambda r: float(r.get("_score") or 0), reverse=True)
    return rows


# Cond re-export keeps static_conds typed for merge_and
_ = Cond
