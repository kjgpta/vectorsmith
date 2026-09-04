"""Weaviate adapter."""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar
from urllib.parse import urlparse

from vectorsmith_core.adapters.base import RowBatch, SearchRequest, VectorBackendAdapter
from vectorsmith_core.adapters.capabilities import WEAVIATE_CAPS
from vectorsmith_core.errors import BackendUnreachable, InvalidArgumentsError
from vectorsmith_core.ir.filter import And, Cond, IRNode, Or


class WeaviateAdapter(VectorBackendAdapter):
    caps: ClassVar = WEAVIATE_CAPS

    def __init__(self, creds: dict[str, str]) -> None:
        self.url = creds.get("url", "")
        self.api_key = creds.get("api_key")
        self.tenant = creds.get("tenant")
        self.embedding_mode = creds.get("embedding_mode", "auto")
        self._client: Any = None
        self._native_cache: dict[str, dict[str, Any]] = {}

    def compile_filter(self, node: IRNode | None) -> object:
        if node is None:
            return None
        try:
            from weaviate.classes.query import Filter
        except ImportError as exc:
            raise BackendUnreachable(
                detail="weaviate extra not installed: pip install vectorsmith-core[weaviate]"
            ) from exc
        if isinstance(node, Cond):
            if "." in node.path:
                raise InvalidArgumentsError(
                    detail="Weaviate does not support nested object filter paths"
                )
            prop: Any = (
                Filter.by_id() if node.path == "id" else Filter.by_property(node.path)
            )
            value: Any = node.value
            if node.op == "eq":
                return prop.equal(value)
            if node.op == "ne":
                return prop.not_equal(value)
            if node.op == "gt":
                return prop.greater_than(value)
            if node.op == "gte":
                return prop.greater_or_equal(value)
            if node.op == "lt":
                return prop.less_than(value)
            if node.op == "lte":
                return prop.less_or_equal(value)
            if node.op == "like":
                pattern = str(node.value).replace("%", "*").replace("_", "?")
                return prop.like(pattern)
            if node.op == "text_match":
                return prop.like(f"*{node.value}*")
            if node.op in {"contains_any", "contains_all"}:
                array_values = (
                    list(node.value)
                    if isinstance(node.value, (list, tuple, set))
                    else [node.value]
                )
                if not array_values:
                    raise InvalidArgumentsError(
                        detail=f"Weaviate '{node.op}' requires values"
                    )
                method = getattr(prop, node.op, None)
                if not callable(method):
                    raise InvalidArgumentsError(
                        detail=f"Weaviate client does not support '{node.op}'"
                    )
                return method(array_values)
            if node.op in {"in", "nin"}:
                membership_values = (
                    node.value
                    if isinstance(node.value, (list, tuple, set))
                    else [node.value]
                )
                pieces = [
                    (
                        prop.equal(value)
                        if node.op == "in"
                        else prop.not_equal(value)
                    )
                    for value in membership_values
                ]
                if not pieces:
                    raise InvalidArgumentsError(detail=f"Weaviate '{node.op}' needs values")
                combined = pieces[0]
                for piece in pieces[1:]:
                    combined = (combined | piece) if node.op == "in" else (combined & piece)
                return combined
            raise InvalidArgumentsError(detail=f"Weaviate does not support op '{node.op}'")
        if isinstance(node, And):
            and_filters: list[Any] = [
                self.compile_filter(child) for child in node.children
            ]
            if not and_filters:
                return None
            combined = and_filters[0]
            for item in and_filters[1:]:
                combined &= item
            return combined
        if isinstance(node, Or):
            or_filters: list[Any] = [
                self.compile_filter(child) for child in node.children
            ]
            if not or_filters:
                return None
            combined = or_filters[0]
            for item in or_filters[1:]:
                combined |= item
            return combined
        raise InvalidArgumentsError(detail="invalid Weaviate filter")

    def _sdk(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import weaviate
            from weaviate.auth import AuthApiKey
        except ImportError as exc:
            raise BackendUnreachable(
                detail="weaviate extra not installed: pip install vectorsmith-core[weaviate]"
            ) from exc
        auth = AuthApiKey(self.api_key) if self.api_key else None
        parsed = urlparse(self.url if "://" in self.url else f"http://{self.url}")
        host = parsed.hostname or "localhost"
        secure = parsed.scheme == "https"
        self._client = weaviate.connect_to_custom(
            http_host=host,
            http_port=parsed.port or (443 if secure else 8080),
            http_secure=secure,
            grpc_host=host,
            grpc_port=50051,
            grpc_secure=secure,
            auth_credentials=auth,
        )
        return self._client

    async def health(self) -> bool:
        try:
            return bool(await asyncio.to_thread(self._sdk().is_ready))
        except BackendUnreachable:
            raise
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc

    async def list_collections(self) -> list[str]:
        try:
            cols = await asyncio.to_thread(self._sdk().collections.list_all)
            if isinstance(cols, dict):
                return list(cols)
            return [getattr(c, "name", str(c)) for c in cols]
        except BackendUnreachable:
            raise
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc

    async def search(self, req: SearchRequest) -> RowBatch:
        from weaviate.classes.query import MetadataQuery

        native_filter = self.compile_filter(
            req.filter_ir if isinstance(req.filter_ir, (And, Or, Cond)) else None
        )
        return_properties = list(req.projection) if req.projection else None
        metadata = MetadataQuery(
            distance=req.with_score,
            certainty=req.with_score,
            score=req.with_score,
        )

        def execute() -> Any:
            coll = self._sdk().collections.get(req.collection)
            if self.tenant:
                coll = coll.with_tenant(self.tenant)
            common = {
                "limit": req.limit,
                "offset": req.offset or 0,
                "filters": native_filter,
                "return_properties": return_properties,
                "return_metadata": metadata,
            }
            if req.mode == "hybrid" and req.query_text:
                hybrid_args: dict[str, Any] = {
                    "query": req.query_text,
                    "alpha": req.alpha,
                    **common,
                }
                if req.vector is not None:
                    hybrid_args["vector"] = req.vector
                return coll.query.hybrid(**hybrid_args)
            if req.vector is None and req.query_text:
                return coll.query.near_text(query=req.query_text, **common)
            if req.vector is None:
                return coll.query.fetch_objects(**common)
            return coll.query.near_vector(near_vector=req.vector, **common)

        try:
            res = await asyncio.to_thread(execute)
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc
        rows = []
        for obj in getattr(res, "objects", []) or []:
            props = dict(getattr(obj, "properties", None) or {})
            row = {**props, "_id": str(getattr(obj, "uuid", ""))}
            if req.with_score and (req.vector is not None or req.query_text):
                meta = getattr(obj, "metadata", None)
                score = (
                    getattr(meta, "score", None)
                    or getattr(meta, "certainty", None)
                )
                distance = getattr(meta, "distance", None)
                if score is None and isinstance(distance, (int, float)):
                    score = 1.0 / (1.0 + max(0.0, float(distance)))
                if isinstance(score, (int, float)):
                    row["_score"] = float(score)
            rows.append(row)
        return RowBatch(rows=rows, exhausted=len(rows) < req.limit)

    async def count(self, collection: str, filter_ir: IRNode | None) -> int:
        native_filter = self.compile_filter(filter_ir)

        def aggregate() -> Any:
            coll = self._sdk().collections.get(collection)
            if self.tenant:
                coll = coll.with_tenant(self.tenant)
            return coll.aggregate.over_all(total_count=True, filters=native_filter)

        try:
            agg = await asyncio.to_thread(aggregate)
            total = getattr(agg, "total_count", 0)
            return int(getattr(total, "real", 0) or total or 0)
        except BackendUnreachable:
            raise
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc

    async def sample(self, collection: str, n: int) -> list[dict[str, Any]]:
        batch = await self.search(SearchRequest(collection=collection, limit=n))
        return batch.rows

    async def introspect_native(self, collection: str | None = None) -> dict[str, Any] | None:
        if collection is None:
            return None
        if collection in self._native_cache:
            return dict(self._native_cache[collection])

        def inspect() -> Any:
            coll = self._sdk().collections.get(collection)
            if self.tenant:
                coll = coll.with_tenant(self.tenant)
            return coll.config.get()

        try:
            config = await asyncio.to_thread(inspect)
        except Exception as exc:
            raise BackendUnreachable(detail=str(exc)) from exc
        fields = _weaviate_fields(getattr(config, "properties", None) or [])
        vectorizer = _weaviate_vectorizer(config)
        self_provided = vectorizer is None or any(
            token in vectorizer for token in ("none", "self_provided")
        )
        info = {
            "fields": fields,
            "indexed_paths": {
                field["path"]: "filterable"
                for field in fields
                if field.get("indexed")
            },
            "vectorizer": vectorizer,
            "self_provided": self_provided,
            "provenance": "native",
        }
        self._native_cache[collection] = info
        return dict(info)

    async def uses_server_side_embedding(self, collection: str) -> bool:
        if self.embedding_mode == "client":
            return False
        info = await self.introspect_native(collection)
        available = bool(info and not info.get("self_provided", True))
        if self.embedding_mode == "server" and not available:
            raise InvalidArgumentsError(
                detail=f"Weaviate collection '{collection}' has no server-side vectorizer"
            )
        return available

    async def aclose(self) -> None:
        if self._client is not None:
            close = getattr(self._client, "close", None)
            if close:
                await asyncio.to_thread(close)
            self._client = None


def _weaviate_fields(properties: object, prefix: str = "") -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for prop in properties if isinstance(properties, (list, tuple)) else []:
        name = str(getattr(prop, "name", "") or "")
        if not name:
            continue
        path = f"{prefix}.{name}" if prefix else name
        raw_type = getattr(prop, "data_type", None)
        dtype = _weaviate_dtype(raw_type)
        indexed = bool(
            getattr(prop, "index_filterable", False)
            or getattr(prop, "index_searchable", False)
        )
        fields.append(
            {
                "path": path,
                "dtype": dtype,
                "nullable": True,
                "indexed": indexed,
                "provenance": "native",
            }
        )
        nested = getattr(prop, "nested_properties", None) or []
        fields.extend(_weaviate_fields(nested, path))
    return fields


def _weaviate_dtype(value: object) -> str:
    text = str(getattr(value, "value", value) or "").lower()
    if "[]" in text or text.endswith("_array"):
        return "keyword[]"
    if any(token in text for token in ("int", "number")):
        return "integer" if "int" in text else "float"
    if "bool" in text:
        return "boolean"
    if "date" in text:
        return "datetime"
    return "keyword"


def _weaviate_vectorizer(config: object) -> str | None:
    vector_config = getattr(config, "vector_config", None)
    if isinstance(vector_config, dict) and vector_config:
        first = next(iter(vector_config.values()))
        vectorizer = getattr(first, "vectorizer", None)
        if vectorizer is not None:
            return str(getattr(vectorizer, "vectorizer", None) or vectorizer).lower()
    legacy = getattr(config, "vectorizer_config", None)
    if legacy is not None:
        return str(getattr(legacy, "vectorizer", None) or legacy).lower()
    return None
