"""Milvus adapter."""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from vectorsmith_core.adapters.base import RowBatch, SearchRequest, VectorBackendAdapter
from vectorsmith_core.adapters.capabilities import MILVUS_CAPS
from vectorsmith_core.errors import BackendUnreachable, InvalidArgumentsError
from vectorsmith_core.ir.filter import And, Cond, IRNode, Or


class MilvusAdapter(VectorBackendAdapter):
    caps: ClassVar = MILVUS_CAPS

    def __init__(self, creds: dict[str, str]) -> None:
        self.uri = creds.get("uri", "")
        self.token = creds.get("token")
        self.user = creds.get("user")
        self.password = creds.get("password")
        self.database = creds.get("database") or "default"
        self._client: Any = None

    def compile_filter(self, node: IRNode | None) -> object:
        if node is None:
            return ""
        if isinstance(node, Cond):
            path = _milvus_path(node.path)
            val = node.value
            if isinstance(val, str):
                lit = "'" + val.replace("'", "''") + "'"
            elif isinstance(val, list):
                inner = ", ".join(
                    "'" + str(x).replace("'", "''") + "'" if isinstance(x, str) else str(x)
                    for x in val
                )
                lit = f"[{inner}]"
            else:
                lit = repr(val)
            ops = {
                "eq": "==",
                "ne": "!=",
                "gt": ">",
                "gte": ">=",
                "lt": "<",
                "lte": "<=",
                "in": "in",
                "nin": "not in",
            }
            if node.op not in self.caps.ops:
                raise InvalidArgumentsError(detail=f"Milvus does not support op '{node.op}'")
            if node.op in {"contains_any", "contains_all"}:
                values = val if isinstance(val, list) else [val]
                if not values:
                    raise InvalidArgumentsError(detail=f"Milvus '{node.op}' requires values")
                function = (
                    "ARRAY_CONTAINS_ANY"
                    if node.op == "contains_any"
                    else "ARRAY_CONTAINS_ALL"
                )
                return f"{function}({path}, {lit})"
            if node.op == "like":
                return f"{path} like {lit}"
            op = ops.get(node.op, node.op)
            return f"{path} {op} {lit}"
        if isinstance(node, And):
            return " and ".join(f"({self.compile_filter(c)})" for c in node.children)
        if isinstance(node, Or):
            return " or ".join(f"({self.compile_filter(c)})" for c in node.children)
        return ""

    def _sdk(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from pymilvus import MilvusClient
        except ImportError as exc:
            raise BackendUnreachable(
                detail="milvus extra not installed: pip install vectorsmith-core[milvus]"
            ) from exc
        kwargs: dict[str, Any] = {"uri": self.uri, "db_name": self.database}
        if self.token:
            kwargs["token"] = self.token
        if self.user:
            kwargs["user"] = self.user
            kwargs["password"] = self.password
        self._client = MilvusClient(**kwargs)
        return self._client

    async def health(self) -> bool:
        try:
            await asyncio.to_thread(self._sdk().list_collections)
            return True
        except BackendUnreachable:
            raise
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc

    async def list_collections(self) -> list[str]:
        try:
            return list(await asyncio.to_thread(self._sdk().list_collections))
        except BackendUnreachable:
            raise
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc

    async def search(self, req: SearchRequest) -> RowBatch:
        expr = self.compile_filter(
            req.filter_ir if isinstance(req.filter_ir, (And, Or, Cond)) else None
        )
        if req.mode == "hybrid":
            raise InvalidArgumentsError(detail="Milvus hybrid search is not implemented")
        if req.vector is None:
            try:
                rows = await asyncio.to_thread(
                    self._sdk().query,
                    collection_name=req.collection,
                    filter=expr or "",
                    limit=req.limit,
                    offset=req.offset or 0,
                    output_fields=list(req.projection) if req.projection else ["*"],
                )
            except Exception as exc:
                raise BackendUnreachable(detail=str(exc)) from exc
            normalized = [_milvus_query_row(row) for row in rows or []]
            return RowBatch(rows=normalized, exhausted=len(normalized) < req.limit)
        try:
            if req.offset is not None:
                raise InvalidArgumentsError(
                    detail="Milvus does not support deterministic vector search offsets"
                )
            hits = await asyncio.to_thread(
                self._sdk().search,
                collection_name=req.collection,
                data=[req.vector],
                limit=req.limit,
                filter=expr or "",
                output_fields=list(req.projection) if req.projection else ["*"],
            )
            metric = await asyncio.to_thread(_milvus_metric, self._sdk(), req.collection)
        except InvalidArgumentsError:
            raise
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc
        rows = []
        first = hits[0] if hits else []
        for h in first:
            entity = dict(h.get("entity") or h)
            entity["_id"] = h.get("id")
            if req.with_score:
                score = _milvus_score(h.get("distance"), metric)
                if score is not None:
                    entity["_score"] = score
            rows.append(entity)
        return RowBatch(rows=rows, exhausted=True)

    async def count(self, collection: str, filter_ir: IRNode | None) -> int:
        expr = self.compile_filter(filter_ir)
        try:
            rows = await asyncio.to_thread(
                self._sdk().query,
                collection_name=collection,
                filter=expr or "",
                output_fields=["count(*)"],
            )
            if not rows:
                return 0
            first = rows[0] if isinstance(rows, list) else rows
            if isinstance(first, dict):
                for key in ("count(*)", "count", "row_count"):
                    if key in first:
                        return int(first[key])
            raise ValueError(f"malformed Milvus count response: {rows!r}")
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc

    async def sample(self, collection: str, n: int) -> list[dict[str, Any]]:
        batch = await self.search(SearchRequest(collection=collection, limit=n))
        return batch.rows

    async def introspect_native(self, collection: str | None = None) -> dict[str, Any] | None:
        if collection is None:
            return None
        try:
            description = await asyncio.to_thread(
                self._sdk().describe_collection,
                collection_name=collection,
            )
            index_names = await asyncio.to_thread(
                self._sdk().list_indexes,
                collection_name=collection,
            )
            indexes = []
            for name in index_names or []:
                indexes.append(
                    await asyncio.to_thread(
                        self._sdk().describe_index,
                        collection_name=collection,
                        index_name=name,
                    )
                )
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc
        raw_fields = description.get("fields", []) if isinstance(description, dict) else []
        indexed_paths = {
            str(index.get("field_name")): str(index.get("index_type") or "index")
            for index in indexes
            if isinstance(index, dict) and index.get("field_name")
        }
        fields: list[dict[str, Any]] = []
        dim: int | None = None
        for field in raw_fields:
            if not isinstance(field, dict):
                continue
            name = str(field.get("name") or field.get("field_name") or "")
            if not name:
                continue
            params = field.get("params") if isinstance(field.get("params"), dict) else {}
            raw_dim = (params or {}).get("dim")
            raw_type = field.get("type") or field.get("data_type")
            if raw_dim is not None:
                try:
                    dim = int(raw_dim)
                except (TypeError, ValueError):
                    pass
            if "vector" in str(raw_type).lower():
                continue
            fields.append(
                {
                    "path": name,
                    "dtype": _milvus_dtype(raw_type),
                    "nullable": bool(field.get("nullable", True)),
                    "indexed": name in indexed_paths,
                    "provenance": "native",
                }
            )
        return {
            "dim": dim,
            "sparse": False,
            "fields": fields,
            "indexed_paths": indexed_paths,
            "provenance": "native",
        }

    async def aclose(self) -> None:
        if self._client is not None:
            close = getattr(self._client, "close", None)
            if callable(close):
                await asyncio.to_thread(close)
            self._client = None


def _milvus_path(path: str) -> str:
    """Render a top-level field or nested dynamic JSON path."""
    head, *tail = path.split(".")
    return head + "".join(f'["{part}"]' for part in tail)


def _milvus_dtype(value: object) -> str:
    text = str(getattr(value, "name", value) or "").lower()
    if "vector" in text:
        return "unknown"
    if "array" in text:
        return "keyword[]"
    if "bool" in text:
        return "boolean"
    if any(token in text for token in ("float", "double")):
        return "float"
    if "int" in text:
        return "integer"
    return "keyword"


def _milvus_query_row(value: object) -> dict[str, Any]:
    row = dict(value) if isinstance(value, dict) else {}
    if "_id" not in row:
        for key in ("id", "pk"):
            if key in row:
                row["_id"] = row[key]
                row.pop(key, None)
                break
    return row


def _milvus_metric(client: Any, collection: str) -> str:
    indexes = client.list_indexes(collection_name=collection)
    if not indexes:
        return "COSINE"
    description = client.describe_index(collection_name=collection, index_name=indexes[0])
    params = description.get("index_param") if isinstance(description, dict) else None
    metric = (
        (params or {}).get("metric_type")
        if isinstance(params, dict)
        else description.get("metric_type") if isinstance(description, dict) else None
    )
    return str(metric or "COSINE").upper()


def _milvus_score(value: object, metric: str) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    distance = float(value)
    if metric in {"L2", "EUCLIDEAN", "HAMMING", "JACCARD"}:
        return 1.0 / (1.0 + max(0.0, distance))
    return distance
