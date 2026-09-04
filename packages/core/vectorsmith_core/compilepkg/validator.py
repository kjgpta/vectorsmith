"""Collect-all TDS validator. Codes are stable (tech Appendix B)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from typing import Any, Literal

from vectorsmith_core.adapters.capabilities import CAPS_BY_BACKEND, Capabilities
from vectorsmith_core.tds.models import (
    EmbeddingConfig,
    PgvectorConn,
    QuerySpec,
    RetrieveStep,
    TDSFile,
    ToolSpec,
    is_table_mode,
)

RESERVED = frozenset(
    {
        "ping",
        "define_tool",
        "describe_collection",
        "list_available_tools",
        "run_tool",
        "list_my_connections",
        "get_started",
    }
)
TENANT_RE = re.compile(
    r"^(tenant|org(_id)?|organization_id|customer_id|account_id|workspace(_id)?)$"
)

DTYPE_OPS: dict[str, frozenset[str]] = {
    "keyword": frozenset({"eq", "ne", "in", "nin", "like", "text_match"}),
    "integer": frozenset({"eq", "ne", "gt", "gte", "lt", "lte", "in", "nin"}),
    "float": frozenset({"eq", "ne", "gt", "gte", "lt", "lte", "in", "nin"}),
    "datetime": frozenset({"eq", "ne", "gt", "gte", "lt", "lte", "in", "nin"}),
    "boolean": frozenset({"eq", "ne"}),
    "keyword[]": frozenset({"in", "nin", "contains_any", "contains_all"}),
    "unknown": frozenset(),
}

GATED_OPS = frozenset({"exists", "is_null", "contains_any", "contains_all", "like", "text_match"})


def _issue(
    code: str,
    message: str,
    *,
    severity: Literal["error", "warning"] = "error",
    tool: str | None = None,
    path: str | None = None,
) -> Any:
    from vectorsmith_core.api import Issue

    return Issue(severity=severity, code=code, message=message, tool=tool, path=path)


def _enabled_builtin_names(tds: TDSFile) -> set[str]:
    names: set[str] = set()
    for cname, conn in tds.connections.items():
        bt = conn.builtin_tools
        if bt.semantic_search:
            names.add(f"search_{cname}")
        if bt.get_by_id:
            names.add(f"get_{cname}_by_id")
        if bt.count:
            names.add(f"count_{cname}")
        if bt.list_collections:
            names.add(f"list_{cname}_collections")
    return names


def validate(tds: TDSFile, *, live_sparse: dict[str, bool] | None = None) -> list[Any]:
    """Return all issues. ``live_sparse`` maps ``connection.collection`` → has_sparse."""
    issues: list[Any] = []
    if tds.tds_version == "1":
        issues.append(
            _issue(
                "VB0002",
                "tds_version 1 is deprecated; run `vectorsmith migrate --from 1 --to 2 --dry-run`",
                severity="warning",
            )
        )
    for name, conn in tds.connections.items():
        caps = CAPS_BY_BACKEND.get(conn.backend)
        if caps is not None and caps.support_level == "experimental":
            issues.append(
                _issue(
                    "VB2024",
                    f"backend '{conn.backend}' is experimental; "
                    "verify against your SDK/server versions",
                    severity="warning",
                    path=f"connections.{name}",
                )
            )
    reserved = RESERVED | _enabled_builtin_names(tds)
    seen_params: dict[str, set[str]] = {}

    for tool in tds.tools:
        issues.extend(_validate_tool(tds, tool, reserved, live_sparse))
        names = [p.name for p in tool.parameters]
        if len(names) != len(set(names)):
            issues.append(_issue("VB2002", "duplicate parameter names", tool=tool.name))
        seen_params[tool.name] = set(names)

    issues.extend(_builtin_lints(tds))
    issues.extend(_embed_provider_issues(tds))
    issues.extend(_tenancy_issues(tds))
    issues.extend(_rbac_issues(tds))
    issues.extend(_credential_issues(tds))
    issues.extend(_rerank_provider_issues(tds))
    return issues


def _credential_issues(tds: TDSFile) -> list[Any]:
    issues: list[Any] = []
    for name, conn in tds.connections.items():
        creds = conn.credentials
        path = f"connections.{name}.credentials"
        if creds.provider == "vault" and not creds.vault.path:
            issues.append(
                _issue(
                    "VB4040",
                    f"connection '{name}' credentials.provider vault needs vault.path",
                    path=path,
                )
            )
        if creds.provider == "aws_sm" and not creds.aws_sm.secret_id:
            issues.append(
                _issue(
                    "VB4041",
                    f"connection '{name}' credentials.provider aws_sm needs aws_sm.secret_id",
                    path=path,
                )
            )
        if creds.provider == "k8s" and not creds.k8s.secret:
            issues.append(
                _issue(
                    "VB4042",
                    f"connection '{name}' credentials.provider k8s needs k8s.secret",
                    path=path,
                )
            )
    return issues


def _rerank_provider_issues(tds: TDSFile) -> list[Any]:
    issues: list[Any] = []
    for tool in tds.tools:
        spec = tool.rerank
        if not spec.enabled or spec.provider != "cross_encoder":
            continue
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            issues.append(
                _issue(
                    "VB4032",
                    "rerank.provider cross_encoder requires "
                    "pip install 'vectorsmith[rerank-local]'",
                    tool=tool.name,
                    severity="warning",
                )
            )
    return issues


def _tenancy_issues(tds: TDSFile) -> list[Any]:
    tenancy = tds.security.tenancy
    issues: list[Any] = []
    if tenancy.mode == "claim" and not tenancy.claim:
        issues.append(
            _issue(
                "VB4011",
                "security.tenancy.mode is claim but claim is not set",
            )
        )
    if tenancy.mode in {"claim", "header"}:
        for tool in tds.tools:
            for param in tool.parameters:
                if param.path == tenancy.path or param.name == tenancy.path:
                    issues.append(
                        _issue(
                            "VB4012",
                            f"parameter '{param.name}' collides with tenancy path "
                            f"'{tenancy.path}'",
                            severity="warning",
                            tool=tool.name,
                            path=param.path or param.name,
                        )
                    )
    return issues


def _rbac_issues(tds: TDSFile) -> list[Any]:
    rbac = tds.security.rbac
    issues: list[Any] = []
    if not rbac.enabled:
        return issues
    if not rbac.roles:
        issues.append(_issue("VB4013", "security.rbac.enabled is true but no roles are defined"))
        return issues
    known = {t.name for t in tds.tools} | RESERVED | _enabled_builtin_names(tds)
    for role, spec in rbac.roles.items():
        for name in spec.allow:
            if name == "*":
                continue
            if name not in known:
                issues.append(
                    _issue(
                        "VB4014",
                        f"role '{role}' allows unknown tool '{name}'",
                        severity="warning",
                        tool=name,
                    )
                )
    return issues


def _tool_embed_spec(tds: TDSFile, tool: ToolSpec) -> EmbeddingConfig:
    if tool.query is not None and tool.query.embedding is not None:
        return tool.query.embedding
    if tool.steps:
        first = tool.steps[0]
        if isinstance(first, RetrieveStep) and first.retrieve.query is not None:
            if first.retrieve.query.embedding is not None:
                return first.retrieve.query.embedding
    return tds.defaults.embedding


def _embed_provider_issues(tds: TDSFile) -> list[Any]:
    from vectorsmith_core.embed.registry import provider_available

    issues: list[Any] = []
    seen: set[str] = set()
    specs = [tds.defaults.embedding]
    for tool in tds.tools:
        specs.append(_tool_embed_spec(tds, tool))
    for spec in specs:
        if spec.provider in seen:
            continue
        seen.add(spec.provider)
        if spec.provider in {"openai", "azure_openai", "cohere"} and not provider_available(
            spec.provider
        ):
            extra = "embed-openai" if spec.provider != "cohere" else "embed-cohere"
            issues.append(
                _issue(
                    "VB2019",
                    f"embedding provider '{spec.provider}' is not installed "
                    f"(pip install 'vectorsmith[{extra}]')",
                    path="defaults.embedding.provider",
                )
            )
    return issues


def _conn_for(tds: TDSFile, tool: ToolSpec) -> object | None:
    connection, _ = _target_for(tool)
    if connection is not None:
        return tds.connections.get(connection)
    return None


def _target_for(tool: ToolSpec) -> tuple[str | None, str | None]:
    if tool.target:
        collection = tool.target.collection if isinstance(tool.target.collection, str) else None
        return tool.target.connection, collection
    for step in tool.steps or []:
        if isinstance(step, RetrieveStep):
            target = step.retrieve.target
            collection = target.collection if isinstance(target.collection, str) else None
            return target.connection, collection
    return None, None


def _static_filter_capability_issues(
    filters: object,
    caps: Capabilities | None,
    *,
    tool: str | None = None,
    base_path: str | None = None,
) -> list[Any]:
    """Apply backend path/operator gates to both static-filter branches."""
    issues: list[Any] = []
    if caps is None:
        return issues
    for branch in ("must", "must_not"):
        for static_filter in getattr(filters, branch, None) or []:
            path = static_filter.path
            issue_path = f"{base_path}.{branch}.{path}" if base_path else path
            if static_filter.op not in caps.ops:
                issues.append(
                    _issue(
                        "VB2004",
                        f"backend does not support op '{static_filter.op}'",
                        tool=tool,
                        path=issue_path,
                    )
                )
            if "." in path and not caps.nested_paths:
                issues.append(
                    _issue(
                        "VB2004",
                        "backend does not support nested paths",
                        tool=tool,
                        path=issue_path,
                    )
                )
    return issues


def _validate_tool(
    tds: TDSFile,
    tool: ToolSpec,
    reserved: AbstractSet[str],
    live_sparse: dict[str, bool] | None,
) -> list[Any]:
    issues: list[Any] = []
    if tool.name in reserved and not tool._synthetic:
        issues.append(_issue("VB2010", f"name '{tool.name}' is reserved", tool=tool.name))
    if tool.kind == "meta" and not tool._synthetic:
        issues.append(_issue("VB2014", "user files may not declare kind=meta", tool=tool.name))
    if tool.kind == "meta" and (tool.query or tool.parameters or tool.static_filters):
        issues.append(
            _issue("VB2011", "meta tools cannot have query/params/filters", tool=tool.name)
        )
    lcd = frozenset({"eq", "ne", "gt", "gte", "lt", "lte", "in", "nin"})
    extras = getattr(tool.static_filters, "model_extra", None) or {}
    if extras:
        issues.append(
            _issue(
                "VB2021",
                "static_filters cannot mix a bare list with must/must_not keys",
                tool=tool.name,
            )
        )
    for sf in tool.static_filters.must_not:
        if sf.op not in lcd:
            issues.append(
                _issue(
                    "VB2020",
                    f"must_not op '{sf.op}' is not in the allowed set",
                    tool=tool.name,
                    path=sf.path,
                )
            )

    conn = _conn_for(tds, tool)
    caps = CAPS_BY_BACKEND.get(getattr(conn, "backend", ""), None)
    issues.extend(_static_filter_capability_issues(tool.static_filters, caps, tool=tool.name))

    if tool.kind == "scroll" and (caps is None or not caps.scroll):
        issues.append(
            _issue("VB2004", "backend does not support scroll", tool=tool.name)
        )
    if (
        tool.kind == "count"
        and (tool.parameters or tool.static_filters)
        and (caps is None or not caps.count_with_filter)
    ):
        issues.append(
            _issue("VB2004", "backend does not support filtered count", tool=tool.name)
        )

    if isinstance(conn, PgvectorConn) and is_table_mode(conn):
        if tool.kind == "search" or tool.query is not None:
            issues.append(
                _issue(
                    "VB2016",
                    "this connection has no vector column — table mode supports "
                    "lookup/count/scroll/pipeline",
                    tool=tool.name,
                )
            )

    if tool.kind == "lookup" and tool.output.limit_default != 1:
        issues.append(
            _issue("VB2006", "lookup limit forced to 1", severity="warning", tool=tool.name)
        )

    if tool.target and not isinstance(tool.target.collection, str) and not tool._synthetic:
        issues.append(_issue("VB2015", "ParamRef targets are synthesis-only", tool=tool.name))

    for p in tool.parameters:
        allowed = DTYPE_OPS.get(str(p.dtype), frozenset())
        if p.op and p.op not in allowed:
            issues.append(
                _issue(
                    "VB2001",
                    f"op '{p.op}' is not valid for dtype '{p.dtype}'",
                    tool=tool.name,
                    path=p.path,
                )
            )
        if p.op and caps and p.op in GATED_OPS and p.op not in caps.ops:
            issues.append(
                _issue(
                    "VB2004",
                    f"backend does not support op '{p.op}'",
                    tool=tool.name,
                    path=p.path,
                )
            )
        if p.dtype == "keyword[]" and (caps is None or not caps.arrays):
            issues.append(
                _issue(
                    "VB2004",
                    "backend does not support array filters",
                    tool=tool.name,
                    path=p.path,
                )
            )
        if p.resolve is not None and p.resolve.kind == "directory":
            resolve_conn = (
                tds.connections.get(p.resolve.connection)
                if p.resolve.connection is not None
                else conn
            )
            resolve_caps = CAPS_BY_BACKEND.get(getattr(resolve_conn, "backend", ""), None)
            if resolve_caps is None or not resolve_caps.scroll:
                issues.append(
                    _issue(
                        "VB4021",
                        "resolve.kind directory requires a backend that can scroll",
                        tool=tool.name,
                        path=p.path,
                    )
                )
        if p.enum and p.op not in {None, "eq", "ne", "in", "nin"}:
            issues.append(
                _issue(
                    "VB2005",
                    "enum is unusual with this operator",
                    severity="warning",
                    tool=tool.name,
                    path=p.path,
                )
            )
        if p.path and p.path.count(".") >= 1 and caps and not caps.nested_paths:
            issues.append(
                _issue(
                    "VB2004", "backend does not support nested paths", tool=tool.name, path=p.path
                )
            )

    queries: list[QuerySpec] = []
    if tool.query:
        queries.append(tool.query)
    for step in tool.steps or []:
        if isinstance(step, RetrieveStep) and step.retrieve.query:
            queries.append(step.retrieve.query)
    for q in queries:
        if q.min_score is not None and not 0.0 <= q.min_score <= 1.0:
            issues.append(
                _issue(
                    "VB2022",
                    "min_score must be between 0.0 and 1.0",
                    tool=tool.name,
                )
            )
        elif q.min_score is not None and caps is not None and not caps.score_threshold:
            issues.append(
                _issue(
                    "VB2004",
                    "backend ignores min_score (results are still filtered after fetch)",
                    severity="warning",
                    tool=tool.name,
                )
            )
        if q.ef is not None and (caps is None or not caps.hnsw_ef):
            issues.append(
                _issue(
                    "VB2023",
                    "ef is not supported on this backend and will be ignored",
                    severity="warning",
                    tool=tool.name,
                )
            )
        if q.mode == "hybrid":
            if caps is None or not caps.hybrid:
                issues.append(
                    _issue("VB2012", "hybrid is not supported on this backend", tool=tool.name)
                )
            elif live_sparse is not None and conn is not None:
                connection, coll = _target_for(tool)
                # if we have live knowledge and sparse is False → error
                if (
                    connection is not None
                    and coll is not None
                    and live_sparse.get(f"{connection}:{coll}") is False
                ):
                    issues.append(
                        _issue(
                            "VB2013",
                            "hybrid requires collection sparse vector config",
                            tool=tool.name,
                        )
                    )
            elif live_sparse is None:
                issues.append(
                    _issue(
                        "VB2013",
                        "hybrid requires collection sparse vector config (confirm with --live)",
                        severity="warning",
                        tool=tool.name,
                    )
                )

    if tool.kind == "pipeline":
        if not tool.steps or not isinstance(tool.steps[0], RetrieveStep):
            issues.append(_issue("VB2101", "pipeline must start with retrieve", tool=tool.name))
        for step in tool.steps or []:
            if hasattr(step, "post_filter"):
                expr = step.post_filter.expr
                if not expr or not expr.strip():
                    issues.append(_issue("VB2102", "empty post_filter expr", tool=tool.name))

    desc = tool.description.strip()
    if desc.lower().replace("_", " ") == tool.name.replace("_", " "):
        issues.append(
            _issue(
                "VB3002",
                "description is too close to the tool name",
                severity="warning",
                tool=tool.name,
            )
        )
    if len(desc) < 40:
        issues.append(
            _issue(
                "VB3001",
                "description should tell Claude when to pick this tool",
                severity="warning",
                tool=tool.name,
            )
        )
    return issues


def _builtin_lints(tds: TDSFile) -> list[Any]:
    issues: list[Any] = []
    user_search = {t.name for t in tds.tools if t.kind == "search" and not t._synthetic}
    for cname, conn in tds.connections.items():
        caps = CAPS_BY_BACKEND[conn.backend]
        issues.extend(
            _static_filter_capability_issues(
                conn.builtin_defaults.static_filters,
                caps,
                base_path=f"connections.{cname}.builtin_defaults.static_filters",
            )
        )
        if conn.builtin_tools.get_by_id and not caps.id_lookup:
            issues.append(
                _issue(
                    "VB2025",
                    f"backend '{conn.backend}' cannot preserve guardrails for exact-ID lookup",
                    tool=f"get_{cname}_by_id",
                )
            )
        if (
            conn.builtin_tools.count
            and conn.builtin_defaults.static_filters
            and not caps.count_with_filter
        ):
            issues.append(
                _issue(
                    "VB2025",
                    f"backend '{conn.backend}' does not support filtered count",
                    tool=f"count_{cname}",
                )
            )
        if not conn.builtin_tools.semantic_search:
            continue
        bname = f"search_{cname}"
        if user_search:
            issues.append(
                _issue(
                    "VB3003",
                    f"unrestricted built-in {bname} may overlap user search tools",
                    severity="warning",
                    tool=bname,
                )
            )
        bd = conn.builtin_defaults
        if not bd.static_filters and (bd.collections is None or len(bd.collections) != 1):
            # heuristic: we cannot see payload fields here; warn if names look tenant-ish
            # near-miss fixtures must not trigger — only exact reserved field names in defaults
            for sf in bd.static_filters:
                if TENANT_RE.match(sf.path):
                    break
            else:
                issues.append(
                    _issue(
                        "VB3004",
                        "unrestricted semantic_search without tenant static filters",
                        severity="warning",
                        tool=bname,
                    )
                )
        if bd.descriptions:
            for key, text in bd.descriptions.items():
                if len(text) < 20:
                    issues.append(
                        _issue(
                            "VB3005",
                            f"built-in description override for {key} is too short",
                            severity="warning",
                            tool=f"{key}_{cname}",
                        )
                    )
    return issues


_SKIP_PATHS = frozenset({"id", "_id", "_score"})


def _normalized_indexed_paths(info: Mapping[str, Any]) -> set[str] | None:
    """Read the normalized live-introspection index field when provided."""
    raw = info.get("indexed_paths")
    if isinstance(raw, Mapping):
        return {str(path) for path in raw}
    if isinstance(raw, (list, tuple, set, frozenset)):
        return {str(path) for path in raw}
    return None


def embedding_dim(model: str, *, dims: int | None = None) -> int | None:
    """Known model size, explicit ``dims``, or None if unknown."""
    from vectorsmith_core.embed.models import resolve_dims
    from vectorsmith_core.errors import EmbeddingError

    if dims is not None:
        return dims
    try:
        return resolve_dims(model)
    except EmbeddingError:
        return None


def live_contract_issues(
    tds: TDSFile,
    plans: Mapping[str, Any],
    native: Mapping[str, Mapping[str, Any]],
) -> list[Any]:
    """Embedding dim + payload-path checks using live introspect (``validate --live``).

    ``plans`` maps tool name → ``ExecutionPlan``. ``native`` maps
    ``connection:collection`` → ``{dim, fields, sparse}``.
    """
    from vectorsmith_core.compilepkg.compiler import ExecutionPlan
    from vectorsmith_core.ir.filter import ir_paths

    issues: list[Any] = []
    default_spec = tds.defaults.embedding
    default_model = default_spec.identity
    for name, plan in plans.items():
        if not isinstance(plan, ExecutionPlan):
            continue
        coll = plan.collection if isinstance(plan.collection, str) else None
        if not plan.connection or not coll:
            continue
        key = f"{plan.connection}:{coll}"
        info = native.get(key)
        if not info:
            continue
        conn = tds.connections.get(plan.connection)
        server_embedding = (
            getattr(conn, "backend", None) == "weaviate"
            and getattr(conn, "embedding_mode", "auto") != "client"
            and not bool(info.get("self_provided", True))
        )
        spec = plan.embed_spec or default_spec
        model = plan.embedding or spec.identity or default_model
        if plan.kind in {"search", "pipeline"} and not server_embedding:
            dim = embedding_dim(str(model), dims=spec.dims)
            live_dim = info.get("dim")
            if dim is None:
                issues.append(
                    _issue(
                        "VB2018",
                        f"unknown embedding model '{model}' — cannot check collection dim",
                        severity="warning",
                        tool=name,
                    )
                )
            elif isinstance(live_dim, int) and live_dim != dim:
                issues.append(
                    _issue(
                        "VB2017",
                        f"collection dim {live_dim} != embedder '{model}' ({dim})",
                        tool=name,
                        path=coll,
                    )
                )
        filter_paths: set[str] = set()
        for cond in plan.static_conds:
            filter_paths |= ir_paths(cond)
        for cond in getattr(plan, "static_must_not", None) or []:
            filter_paths |= ir_paths(cond)
        for cond in plan.param_conds:
            filter_paths |= ir_paths(cond)
        caps = CAPS_BY_BACKEND.get(getattr(conn, "backend", ""), None)
        indexed_paths = _normalized_indexed_paths(info)
        if caps is not None and caps.requires_explicit_index and indexed_paths is not None:
            for path in sorted(filter_paths - _SKIP_PATHS - indexed_paths):
                issues.append(
                    _issue(
                        "VB2026",
                        f"filter path '{path}' has no explicit index on collection '{coll}'",
                        tool=name,
                        path=path,
                    )
                )
        fields = info.get("fields")
        if not isinstance(fields, list) or not fields:
            continue
        field_set = {
            str(field.get("path") or field.get("name") or "")
            if isinstance(field, Mapping)
            else str(field)
            for field in fields
        }
        field_set.discard("")
        wanted = filter_paths | {p for p in (plan.projection or []) if p}
        for path in sorted(wanted - _SKIP_PATHS):
            head = path.split(".", 1)[0]
            if path not in field_set and head not in field_set:
                issues.append(
                    _issue(
                        "VB4004",
                        f"payload path '{path}' was not seen on collection '{coll}'",
                        severity="warning",
                        tool=name,
                        path=path,
                    )
                )
    return issues
