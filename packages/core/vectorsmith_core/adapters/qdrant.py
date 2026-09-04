"""Qdrant adapter — dense (+ hybrid when sparse is configured)."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, ClassVar

from vectorsmith_core.adapters.base import RowBatch, SearchRequest, VectorBackendAdapter
from vectorsmith_core.adapters.capabilities import QDRANT_CAPS
from vectorsmith_core.errors import BackendUnreachable, InvalidArgumentsError
from vectorsmith_core.ir.filter import And, Cond, IRNode, Or


def _payload_arg(projection: list[str] | None) -> Any:
    if not projection:
        return True
    from qdrant_client.http import models as qm

    selector = getattr(qm, "PayloadSelectorInclude", None)
    if selector is None:
        return True
    return selector(include=list(projection))


def _vector_dim(info: Any) -> int | None:
    cfg = getattr(info, "config", None)
    params = getattr(cfg, "params", cfg)
    vectors = getattr(params, "vectors", None) if params is not None else None
    size = getattr(vectors, "size", None)
    if isinstance(size, int):
        return size
    if isinstance(vectors, dict) and vectors:
        first = next(iter(vectors.values()))
        n = getattr(first, "size", None)
        if isinstance(n, int):
            return n
        if isinstance(first, dict) and isinstance(first.get("size"), int):
            return int(first["size"])
    return None


def _qdrant_dtype(value: object) -> str:
    text = str(getattr(value, "data_type", value) or "").lower()
    if "integer" in text:
        return "integer"
    if "float" in text:
        return "float"
    if "bool" in text:
        return "boolean"
    if "datetime" in text:
        return "datetime"
    return "keyword"


def _match(cond: Cond) -> dict[str, Any]:
    path, op, value = cond.path, cond.op, cond.value
    if op in {"eq"}:
        return {"key": path, "match": {"value": value}}
    if op == "ne":
        return {"must_not": [{"key": path, "match": {"value": value}}]}
    if op == "in":
        return {"key": path, "match": {"any": value}}
    if op == "nin":
        return {"key": path, "match": {"except": value}}
    if op == "contains_any":
        return {"key": path, "match": {"any": value}}
    if op == "contains_all":
        values = value if isinstance(value, (list, tuple, set)) else [value]
        if not values:
            raise InvalidArgumentsError(detail="contains_all requires at least one value")
        return {
            "must": [{"key": path, "match": {"value": item}} for item in values]
        }
    if op in {"gt", "gte", "lt", "lte"}:
        rng: dict[str, Any] = {}
        if op == "gt":
            rng["gt"] = value
        elif op == "gte":
            rng["gte"] = value
        elif op == "lt":
            rng["lt"] = value
        else:
            rng["lte"] = value
        return {"key": path, "range": rng}
    if op == "exists":
        return (
            {"must_not": [{"is_empty": {"key": path}}]}
            if value
            else {"is_empty": {"key": path}}
        )
    if op == "is_null":
        return (
            {"is_null": {"key": path}}
            if value is not False
            else {"must_not": [{"is_null": {"key": path}}]}
        )
    if op == "text_match":
        return {"key": path, "match": {"text": str(value)}}
    raise BackendUnreachable(detail=f"unsupported op {op}")  # should be VB2004 earlier


class QdrantAdapter(VectorBackendAdapter):
    caps: ClassVar = QDRANT_CAPS

    def __init__(self, url: str, api_key: str | None = None) -> None:
        self.url = url
        self.api_key = api_key
        self._client: Any = None
        self._sparse_model: Any = None

    def _sdk(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from qdrant_client import AsyncQdrantClient
        except ImportError as exc:
            raise BackendUnreachable(
                detail="qdrant extra not installed: pip install vectorsmith-core[qdrant]"
            ) from exc
        from urllib.parse import urlparse

        parsed = urlparse(self.url)
        if parsed.port is not None:
            port = parsed.port
        elif parsed.scheme == "https":
            port = 443
        else:
            port = 6333
        key = self.api_key or None
        kwargs: dict[str, Any] = {
            "url": self.url,
            "api_key": key,
            "port": port,
            "prefer_grpc": False,
            "timeout": 60,
        }
        if "check_compatibility" in inspect.signature(AsyncQdrantClient).parameters:
            kwargs["check_compatibility"] = False
        self._client = AsyncQdrantClient(**kwargs)
        return self._client

    def compile_filter(self, node: IRNode | None) -> object:
        if node is None:
            return None
        if isinstance(node, Cond):
            piece = _match(node)
            if "must_not" in piece:
                return {"must_not": piece["must_not"]}
            if "must" in piece:
                return {"must": piece["must"]}
            return {"must": [piece]}
        if isinstance(node, And):
            must: list[Any] = []
            must_not: list[Any] = []
            for child in node.children:
                compiled = self.compile_filter(child)
                if not isinstance(compiled, dict):
                    continue
                must.extend(compiled.get("must") or [])
                must_not.extend(compiled.get("must_not") or [])
                if "should" in compiled:
                    must.append({"should": compiled["should"]})
            out: dict[str, Any] = {}
            if must:
                out["must"] = must
            if must_not:
                out["must_not"] = must_not
            return out or None
        if isinstance(node, Or):
            return {"should": [self.compile_filter(c) for c in node.children]}
        return None

    async def health(self) -> bool:
        try:
            await self._sdk().get_collections()
            return True
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc

    async def list_collections(self) -> list[str]:
        try:
            res = await self._sdk().get_collections()
            return [c.name for c in res.collections]
        except BackendUnreachable:
            raise
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc

    async def search(self, req: SearchRequest) -> RowBatch:
        try:
            return await self._search(req)
        except (BackendUnreachable, InvalidArgumentsError):
            raise
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc

    async def _search(self, req: SearchRequest) -> RowBatch:
        if req.vector is not None and req.offset is not None:
            raise InvalidArgumentsError(detail="Qdrant does not support offsets for vector search")
        client = self._sdk()
        filter_ir = req.filter_ir if isinstance(req.filter_ir, (And, Or, Cond)) else None
        point_id, remaining_filter, impossible = _split_lookup_id(filter_ir)
        if impossible:
            return RowBatch(rows=[], exhausted=True)
        if req.vector is not None:
            point_id = None
            remaining_filter = filter_ir
        qfilter = self.compile_filter(remaining_filter)
        if point_id is not None:
            assert isinstance(qfilter, (dict, type(None)))
            qfilter = dict(qfilter or {})
            qfilter["must"] = [*(qfilter.get("must") or []), {"has_id": [point_id]}]
        from qdrant_client.http import models as qm

        native = None
        if isinstance(qfilter, dict):
            native = qm.Filter(**qfilter)
        if req.mode == "hybrid":
            native_info = await self.introspect_native(req.collection)
            if not native_info or not native_info.get("sparse"):
                raise BackendUnreachable(
                    detail="VB2013 hybrid requires collection sparse vector config"
                )
            return await self._hybrid_search(client, req, native)
        if req.vector is None:
            fetch_limit = req.limit + (req.offset or 0)
            points, _ = await client.scroll(
                collection_name=req.collection,
                scroll_filter=native,
                limit=fetch_limit,
                with_payload=_payload_arg(req.projection),
                with_vectors=False,
            )
            rows = [_row(p, None) for p in points[req.offset or 0 :]]
            return RowBatch(rows=rows, exhausted=len(points) < fetch_limit)
        extra: dict[str, Any] = {}
        if req.min_score is not None:
            extra["score_threshold"] = req.min_score
        if req.search_ef is not None:
            extra["search_params"] = qm.SearchParams(hnsw_ef=req.search_ef)
        if hasattr(client, "query_points"):
            res = await client.query_points(
                collection_name=req.collection,
                query=req.vector,
                query_filter=native,
                limit=req.limit,
                with_payload=_payload_arg(req.projection),
                **extra,
            )
            hits = getattr(res, "points", res)
        else:
            hits = await client.search(
                collection_name=req.collection,
                query_vector=req.vector,
                query_filter=native,
                limit=req.limit,
                with_payload=_payload_arg(req.projection),
                **extra,
            )
        rows = [
            _row(h, getattr(h, "score", None) if req.with_score else None)
            for h in hits
        ]
        return RowBatch(rows=rows, exhausted=True)

    async def _hybrid_search(self, client: Any, req: SearchRequest, native: object) -> RowBatch:
        from qdrant_client.http import models as qm

        prefetch = []
        if req.vector is not None:
            prefetch.append(qm.Prefetch(query=req.vector, limit=max(req.limit * 2, 20)))
        if req.query_text:
            sparse = await asyncio.to_thread(self._sparse_vector, req.query_text)
            prefetch.append(
                qm.Prefetch(
                    query=qm.SparseVector(
                        indices=[int(value) for value in sparse.indices],
                        values=[float(value) for value in sparse.values],
                    ),
                    using="text",
                    limit=max(req.limit * 2, 20),
                )
            )
        query: object
        if hasattr(qm, "FusionQuery"):
            query = qm.FusionQuery(fusion=qm.Fusion.RRF)
        else:
            query = req.vector
        extra: dict[str, Any] = {}
        if req.min_score is not None:
            extra["score_threshold"] = req.min_score
        if req.search_ef is not None:
            extra["search_params"] = qm.SearchParams(hnsw_ef=req.search_ef)
        res = await client.query_points(
            collection_name=req.collection,
            prefetch=prefetch or None,
            query=query,
            query_filter=native,
            limit=req.limit,
            with_payload=_payload_arg(req.projection),
            **extra,
        )
        hits = getattr(res, "points", res)
        rows = [
            _row(h, getattr(h, "score", None) if req.with_score else None)
            for h in hits
        ]
        return RowBatch(rows=rows, exhausted=True)

    def _sparse_vector(self, text: str) -> Any:
        if self._sparse_model is None:
            try:
                from fastembed import SparseTextEmbedding
            except ImportError as exc:
                raise InvalidArgumentsError(
                    detail="Qdrant hybrid search requires FastEmbed sparse support"
                ) from exc
            self._sparse_model = SparseTextEmbedding("Qdrant/bm25")
        return next(iter(self._sparse_model.embed([text])))

    async def count(self, collection: str, filter_ir: IRNode | None) -> int:
        try:
            qfilter = self.compile_filter(filter_ir)
            from qdrant_client.http import models as qm

            native = qm.Filter(**qfilter) if isinstance(qfilter, dict) else None
            res = await self._sdk().count(collection_name=collection, count_filter=native)
            return int(res.count)
        except BackendUnreachable:
            raise
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc

    async def sample(self, collection: str, n: int) -> list[dict[str, Any]]:
        try:
            points, _ = await self._sdk().scroll(
                collection_name=collection, limit=n, with_payload=True
            )
            return [_row(p, None) for p in points]
        except BackendUnreachable:
            raise
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc

    async def introspect_native(self, collection: str | None = None) -> dict[str, Any] | None:
        if collection is None:
            return None
        info = await self._sdk().get_collection(collection)
        sparse = False
        params = getattr(info, "config", None)
        # sparse vectors appear on collection params when configured
        if params is not None:
            sparse_cfg = getattr(getattr(params, "params", params), "sparse_vectors", None)
            sparse = bool(sparse_cfg)
        payload_schema = getattr(info, "payload_schema", None) or {}
        fields = [
            {
                "path": str(path),
                "dtype": _qdrant_dtype(schema),
                "nullable": True,
                "indexed": True,
                "provenance": "native",
            }
            for path, schema in payload_schema.items()
        ]
        return {
            "sparse": sparse,
            "dim": _vector_dim(info),
            "fields": fields,
            "indexed_paths": {
                str(path): str(getattr(schema, "data_type", schema))
                for path, schema in payload_schema.items()
            },
            "provenance": "native",
        }

    async def aclose(self) -> None:
        if self._client is not None:
            close = getattr(self._client, "close", None)
            if close:
                await close()
            self._client = None


def _split_lookup_id(
    node: IRNode | None,
) -> tuple[int | str | None, IRNode | None, bool]:
    """Extract a native point ID while preserving all conjunctive guardrails."""
    if isinstance(node, Cond):
        if node.path != "id" or node.op != "eq":
            return None, node, False
        value = node.value
        if isinstance(value, bool) or value is None:
            return None, None, True
        if isinstance(value, int):
            return value, None, False
        if isinstance(value, str) and value.isdigit():
            return int(value), None, False
        if isinstance(value, str) and value:
            return value, None, False
        return None, None, True
    if isinstance(node, And):
        point_id: int | str | None = None
        remaining: list[IRNode] = []
        for child in node.children:
            child_id, child_remaining, impossible = _split_lookup_id(child)
            if impossible:
                return None, None, True
            if child_id is not None:
                if point_id is not None and point_id != child_id:
                    return None, None, True
                point_id = child_id
            if child_remaining is not None:
                remaining.append(child_remaining)
        if not remaining:
            rest: IRNode | None = None
        elif len(remaining) == 1:
            rest = remaining[0]
        else:
            rest = And(tuple(remaining))
        return point_id, rest, False
    return None, node, False


def _row(point: Any, score: float | None) -> dict[str, Any]:
    payload = dict(getattr(point, "payload", None) or {})
    pid = getattr(point, "id", None)
    row: dict[str, Any] = {**payload, "_id": pid}
    if score is not None:
        row["_score"] = score
    return row
