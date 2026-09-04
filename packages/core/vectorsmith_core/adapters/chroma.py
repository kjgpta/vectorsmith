"""Chroma adapter — where-dicts, single-condition unwrap."""

from __future__ import annotations

import inspect
import math
from collections.abc import Mapping
from typing import Any, ClassVar
from urllib.parse import urlparse

from vectorsmith_core.adapters.base import RowBatch, SearchRequest, VectorBackendAdapter
from vectorsmith_core.adapters.capabilities import CHROMA_CAPS
from vectorsmith_core.errors import BackendUnreachable, InvalidArgumentsError
from vectorsmith_core.ir.filter import And, Cond, IRNode, Or

_OP = {
    "eq": "$eq",
    "ne": "$ne",
    "gt": "$gt",
    "gte": "$gte",
    "lt": "$lt",
    "lte": "$lte",
    "in": "$in",
    "nin": "$nin",
}
_DOCUMENT_FIELD = "_document"
_COUNT_PAGE_SIZE = 1_000


class ChromaAdapter(VectorBackendAdapter):
    caps: ClassVar = CHROMA_CAPS

    def __init__(self, url: str, auth_token: str | None = None) -> None:
        self.url = url
        self.auth_token = auth_token
        self._client: Any = None

    def compile_filter(self, node: IRNode | None) -> object:
        if node is None:
            return None
        if isinstance(node, Cond):
            if "." in node.path:
                raise InvalidArgumentsError(detail="Chroma does not support nested paths")
            op = _OP.get(node.op)
            if op is None:
                raise InvalidArgumentsError(detail=f"Chroma does not support op '{node.op}'")
            return {node.path: {op: node.value}}
        if isinstance(node, And):
            kids = [
                compiled
                for child in node.children
                if (compiled := self.compile_filter(child)) is not None
            ]
            if not kids:
                return None
            return kids[0] if len(kids) == 1 else {"$and": kids}
        if isinstance(node, Or):
            kids = [
                compiled
                for child in node.children
                if (compiled := self.compile_filter(child)) is not None
            ]
            if not kids:
                return None
            return kids[0] if len(kids) == 1 else {"$or": kids}
        raise InvalidArgumentsError(detail="invalid Chroma filter")

    async def _sdk(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import chromadb
        except ImportError as exc:
            raise BackendUnreachable(
                detail="chroma extra not installed: pip install vectorsmith-core[chroma]"
            ) from exc
        parsed = urlparse(self.url if "://" in self.url else f"http://{self.url}")
        host = parsed.hostname or "localhost"
        ssl = parsed.scheme == "https"
        port = parsed.port or (443 if ssl else 8000)
        headers = None
        if self.auth_token:
            token = self.auth_token.strip()
            if token:
                headers = {
                    "Authorization": (
                        token if token.lower().startswith("bearer ") else f"Bearer {token}"
                    )
                }
        try:
            self._client = await chromadb.AsyncHttpClient(
                host=host,
                port=port,
                ssl=ssl,
                headers=headers,
            )
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc
        return self._client

    async def health(self) -> bool:
        try:
            client = await self._sdk()
            await client.heartbeat()
            return True
        except BackendUnreachable:
            raise
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc

    async def list_collections(self) -> list[str]:
        try:
            client = await self._sdk()
            cols = await client.list_collections()
            return [getattr(c, "name", str(c)) for c in cols]
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
        client = await self._sdk()
        coll = await client.get_collection(req.collection)
        if req.filter_ir is not None and not isinstance(req.filter_ir, (And, Or, Cond)):
            raise InvalidArgumentsError(detail="invalid Chroma filter")
        if req.vector is not None and req.offset is not None:
            raise InvalidArgumentsError(
                detail="Chroma does not support offsets for vector search"
            )
        filter_ir = req.filter_ir if isinstance(req.filter_ir, (And, Or, Cond)) else None
        point_id, remaining_filter, impossible = _split_lookup_id(filter_ir)
        if impossible:
            return RowBatch(rows=[], exhausted=True)
        if req.vector is not None:
            point_id = None
            remaining_filter = filter_ir
        where = self.compile_filter(remaining_filter)
        include = ["metadatas"]
        if req.projection is None or _DOCUMENT_FIELD in req.projection:
            include.append("documents")
        try:
            if req.vector is None:
                kwargs: dict[str, Any] = {
                    "where": where,
                    "limit": req.limit,
                    "include": include,
                }
                if point_id is not None:
                    kwargs["ids"] = [point_id]
                elif req.offset is not None:
                    kwargs["offset"] = req.offset
                res = await coll.get(**kwargs)
            else:
                if req.with_score:
                    include.append("distances")
                res = await coll.query(
                    query_embeddings=[req.vector],
                    n_results=req.limit,
                    where=where,
                    include=include,
                )
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc
        rows = _chroma_rows(res, with_score=req.with_score)
        if req.projection is not None:
            keep = {*req.projection, "_id"}
            if req.with_score and req.vector is not None:
                keep.add("_score")
            rows = [
                {key: value for key, value in row.items() if key in keep}
                for row in rows
            ]
        return RowBatch(rows=rows, exhausted=len(rows) < req.limit)

    async def count(self, collection: str, filter_ir: IRNode | None) -> int:
        try:
            return await self._count(collection, filter_ir)
        except (BackendUnreachable, InvalidArgumentsError):
            raise
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc

    async def _count(self, collection: str, filter_ir: IRNode | None) -> int:
        client = await self._sdk()
        coll = await client.get_collection(collection)
        point_id, remaining_filter, impossible = _split_lookup_id(filter_ir)
        if impossible:
            return 0
        where = self.compile_filter(remaining_filter)
        try:
            if point_id is None and where is None:
                return int(await coll.count())
            if point_id is not None:
                got = await coll.get(ids=[point_id], where=where, limit=1, include=[])
                return len(got.get("ids") or [])
            total = 0
            while True:
                got = await coll.get(
                    where=where,
                    limit=_COUNT_PAGE_SIZE,
                    offset=total,
                    include=[],
                )
                page_count = len(got.get("ids") or [])
                total += page_count
                if page_count < _COUNT_PAGE_SIZE:
                    return total
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc

    async def sample(self, collection: str, n: int) -> list[dict[str, Any]]:
        batch = await self.search(SearchRequest(collection=collection, limit=n))
        return batch.rows

    async def introspect_native(self, collection: str | None = None) -> dict[str, Any] | None:
        if collection is None:
            return None
        return {
            "fields": [],
            "indexed_paths": {},
            "sparse": False,
            "provenance": "sample",
        }

    async def aclose(self) -> None:
        if self._client is None:
            return
        close = getattr(self._client, "close", None)
        if close is not None:
            result = close()
            if inspect.isawaitable(result):
                await result
        self._client = None


def _chroma_rows(res: Any, *, with_score: bool = True) -> list[dict[str, Any]]:
    if isinstance(res, Mapping):
        ids = res.get("ids") or []
        metas = res.get("metadatas") or []
        dists = res.get("distances")
        docs = res.get("documents") or []
        if ids and isinstance(ids[0], list):
            ids, metas = ids[0], (metas[0] if metas else [])
            docs = docs[0] if docs else []
            dists = dists[0] if dists else None
        rows = []
        for i, pid in enumerate(ids):
            meta = metas[i] if i < len(metas) and isinstance(metas[i], dict) else {}
            row = {**meta, "_id": pid}
            if i < len(docs) and isinstance(docs[i], str):
                row[_DOCUMENT_FIELD] = docs[i]
            if with_score and dists is not None and i < len(dists):
                score = _distance_to_score(dists[i])
                if score is not None:
                    row["_score"] = score
            rows.append(row)
        return rows
    return []


def _distance_to_score(value: object) -> float | None:
    """Convert Chroma's lower-is-better distance to a bounded similarity score."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    distance = float(value)
    if not math.isfinite(distance):
        return None
    return 1.0 / (1.0 + max(0.0, distance))


def _split_lookup_id(node: IRNode | None) -> tuple[str | None, IRNode | None, bool]:
    """Extract Chroma's record ID from a conjunctive builtin lookup filter."""
    if isinstance(node, Cond):
        if node.path != "id" or node.op != "eq":
            return None, node, False
        value = node.value
        if isinstance(value, bool) or value is None or not isinstance(value, (str, int)):
            return None, None, True
        single_id = str(value)
        return (single_id, None, False) if single_id else (None, None, True)
    if not isinstance(node, And):
        return None, node, False

    point_id: str | None = None
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
