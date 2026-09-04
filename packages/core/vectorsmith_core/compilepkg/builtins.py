"""Synthesize opt-in built-in tools BEFORE validation (I4 by construction)."""

from __future__ import annotations

from vectorsmith_core.adapters.capabilities import CAPS_BY_BACKEND
from vectorsmith_core.tds.models import (
    OutputSpec,
    ParamSpec,
    QuerySpec,
    Target,
    TDSFile,
    ToolSpec,
)

_TAIL = "and no more specific search tool fits the request"


def _synth(spec: ToolSpec) -> ToolSpec:
    spec._synthetic = True
    return spec


def synthesize(tds: TDSFile, *, sparse: dict[str, bool] | None = None) -> TDSFile:
    """Append synthesized tools after user tools. Idempotent if already present."""
    existing = {t.name for t in tds.tools}
    extra: list[ToolSpec] = []
    for cname, conn in tds.connections.items():
        bt = conn.builtin_tools
        bd = conn.builtin_defaults
        caps = CAPS_BY_BACKEND[conn.backend]
        collections = bd.collections
        static = bd.static_filters
        output = bd.output
        desc_over = bd.descriptions or {}

        def collection_param() -> tuple[Target, list[ParamSpec]]:
            if collections is not None and len(collections) == 1:
                return Target(connection=cname, collection=collections[0]), []
            if collections is not None:
                return (
                    Target(connection=cname, collection="__param__"),
                    [
                        ParamSpec(
                            name="collection",
                            dtype="keyword",
                            required=True,
                            enum=list(collections),
                            description="Collection to query",
                        )
                    ],
                )
            return (
                Target(connection=cname, collection="__param__"),
                [
                    ParamSpec(
                        name="collection",
                        dtype="keyword",
                        required=True,
                        description="Collection to query",
                    )
                ],
            )

        if bt.semantic_search:
            name = f"search_{cname}"
            if name not in existing:
                target, extra_params = collection_param()
                hybrid = False
                if caps.hybrid and sparse:
                    if target.collection != "__param__":
                        hybrid = bool(sparse.get(f"{cname}:{target.collection}", False))
                    elif collections:
                        hybrid = all(
                            sparse.get(f"{cname}:{collection}", False)
                            for collection in collections
                        )
                extra.append(
                    _synth(
                        ToolSpec(
                            name=name,
                            kind="search",
                            description=desc_over.get(
                                "semantic_search",
                                f"Search {cname} by meaning. Use when {_TAIL}",
                            ),
                            target=target,
                            query=QuerySpec(
                                param="query",
                                required=True,
                                mode="hybrid" if hybrid else "dense",
                            ),
                            parameters=extra_params,
                            static_filters=static,
                            output=output if output is not None else OutputSpec(),
                        )
                    )
                )
        if bt.get_by_id:
            name = f"get_{cname}_by_id"
            if name not in existing:
                target, extra_params = collection_param()
                extra.append(
                    _synth(
                        ToolSpec(
                            name=name,
                            kind="lookup",
                            description=desc_over.get(
                                "get_by_id",
                                f"Fetch a {cname} record by exact id. Use when {_TAIL}",
                            ),
                            target=target,
                            parameters=[
                                *extra_params,
                                ParamSpec(
                                    name="id",
                                    path="id",
                                    dtype="keyword",
                                    op="eq",
                                    required=True,
                                    description="Record id",
                                ),
                            ],
                            static_filters=static,
                            output=output or OutputSpec(limit_default=1, limit_max=1),
                        )
                    )
                )
        if bt.count:
            name = f"count_{cname}"
            if name not in existing:
                target, extra_params = collection_param()
                extra.append(
                    _synth(
                        ToolSpec(
                            name=name,
                            kind="count",
                            description=desc_over.get(
                                "count",
                                f"Count {cname} records matching filters. Use when {_TAIL}",
                            ),
                            target=target,
                            parameters=extra_params,
                            static_filters=static,
                        )
                    )
                )
        if bt.list_collections:
            name = f"list_{cname}_collections"
            if name not in existing:
                extra.append(
                    _synth(
                        ToolSpec(
                            name=name,
                            kind="meta",
                            description=desc_over.get(
                                "list_collections",
                                f"List collections on {cname} with approx counts. Use when {_TAIL}",
                            ),
                            target=Target(connection=cname, collection="*"),
                        )
                    )
                )
    if not extra:
        return tds
    return tds.model_copy(update={"tools": list(tds.tools) + extra})
