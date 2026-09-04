"""Pinecone adapter — one connection = one index; collection = namespace."""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from vectorsmith_core.adapters.base import RowBatch, SearchRequest, VectorBackendAdapter
from vectorsmith_core.adapters.capabilities import PINECONE_CAPS
from vectorsmith_core.errors import BackendUnreachable, InvalidArgumentsError
from vectorsmith_core.ir.filter import And, Cond, IRNode, Or


class PineconeAdapter(VectorBackendAdapter):
    caps: ClassVar = PINECONE_CAPS

    def __init__(self, creds: dict[str, str]) -> None:
        self.api_key = creds.get("api_key", "")
        self.host = creds.get("host", "")
        self.namespace = creds.get("namespace")
        self._index: Any = None

    def compile_filter(self, node: IRNode | None) -> object:
        if node is None:
            return None
        if isinstance(node, Cond):
            if "." in node.path:
                raise InvalidArgumentsError(detail="Pinecone does not support nested paths")
            if node.op not in self.caps.ops:
                raise InvalidArgumentsError(detail=f"Pinecone does not support op '{node.op}'")
            values = node.value
            if node.op == "in" and isinstance(values, list) and len(values) > 10_000:
                raise InvalidArgumentsError(detail="Pinecone 'in' supports at most 10,000 values")
            if node.op in {"contains_any", "contains_all"}:
                items = (
                    list(values)
                    if isinstance(values, (list, tuple, set))
                    else [values]
                )
                if not items:
                    raise InvalidArgumentsError(
                        detail=f"Pinecone '{node.op}' requires values"
                    )
                if node.op == "contains_any":
                    return {node.path: {"$in": items}}
                return {
                    "$and": [{node.path: {"$in": [item]}} for item in items]
                }
            return {node.path: {f"${node.op}": values}}
        if isinstance(node, And):
            return {"$and": [self.compile_filter(c) for c in node.children]}
        if isinstance(node, Or):
            return {"$or": [self.compile_filter(c) for c in node.children]}
        return None

    def _sdk(self) -> Any:
        if self._index is not None:
            return self._index
        try:
            from pinecone import Pinecone
        except ImportError as exc:
            raise BackendUnreachable(
                detail="pinecone extra not installed: pip install vectorsmith-core[pinecone]"
            ) from exc
        self._index = Pinecone(api_key=self.api_key).Index(host=self.host)
        return self._index

    async def health(self) -> bool:
        try:
            await asyncio.to_thread(self._sdk().describe_index_stats)
            return True
        except BackendUnreachable:
            raise
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc

    async def list_collections(self) -> list[str]:
        try:
            stats = await asyncio.to_thread(self._sdk().describe_index_stats)
            nss = getattr(stats, "namespaces", None) or {}
            if isinstance(nss, dict):
                return list(nss) or [""]
            return [""]
        except BackendUnreachable:
            raise
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc

    async def search(self, req: SearchRequest) -> RowBatch:
        if req.vector is None:
            raise InvalidArgumentsError(
                detail="Pinecone does not support filter-only lookup or scroll"
            )
        if req.offset is not None:
            raise InvalidArgumentsError(detail="Pinecone does not support vector search offsets")
        if req.mode == "hybrid":
            raise InvalidArgumentsError(detail="Pinecone hybrid search is not implemented")
        ns = req.collection if req.collection != "__param__" else (self.namespace or "")
        try:
            res = await asyncio.to_thread(
                self._sdk().query,
                vector=req.vector,
                top_k=req.limit,
                namespace=ns,
                filter=self.compile_filter(
                    req.filter_ir if isinstance(req.filter_ir, (And, Or, Cond)) else None
                ),
                include_metadata=True,
            )
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc
        matches = getattr(res, "matches", None) or res.get("matches", [])
        rows = []
        for m in matches:
            meta = getattr(m, "metadata", None) or {}
            row = {**dict(meta), "_id": getattr(m, "id", None)}
            if req.projection is not None:
                row = {key: value for key, value in row.items() if key in {*req.projection, "_id"}}
            if req.with_score:
                row["_score"] = getattr(m, "score", None)
            rows.append(row)
        return RowBatch(rows=rows, exhausted=True)

    async def count(self, collection: str, filter_ir: IRNode | None) -> int:
        if filter_ir is not None:
            raise InvalidArgumentsError(detail="Pinecone does not support exact filtered counts")
        try:
            stats = await asyncio.to_thread(self._sdk().describe_index_stats)
            nss = getattr(stats, "namespaces", None) or {}
            if isinstance(nss, dict) and collection in nss:
                ns = nss[collection]
                return int(getattr(ns, "vector_count", 0) or ns.get("vector_count", 0))
            return int(getattr(stats, "total_vector_count", 0) or 0)
        except BackendUnreachable:
            raise
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc

    async def sample(self, collection: str, n: int) -> list[dict[str, Any]]:
        _ = collection, n
        raise InvalidArgumentsError(detail="Pinecone does not support deterministic sampling")

    async def aclose(self) -> None:
        if self._index is not None:
            close = getattr(self._index, "close", None)
            if callable(close):
                await asyncio.to_thread(close)
            self._index = None
