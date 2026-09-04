"""Adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Literal

from pydantic import BaseModel

from vectorsmith_core.adapters.capabilities import Capabilities
from vectorsmith_core.ir.filter import IRNode


class SearchRequest(BaseModel):
    collection: str
    vector: list[float] | None = None
    mode: Literal["dense", "hybrid"] = "dense"
    query_text: str | None = None
    alpha: float = 0.5
    filter_ir: object | None = None
    limit: int = 10
    offset: int | None = None
    projection: list[str] | None = None
    with_score: bool = True
    min_score: float | None = None
    search_ef: int | None = None


class RowBatch(BaseModel):
    rows: list[dict[str, Any]]
    exhausted: bool = True
    scanned: int | None = None


class VectorBackendAdapter(ABC):
    caps: ClassVar[Capabilities]
    vector_capable: bool = True

    @abstractmethod
    async def health(self) -> bool: ...

    @abstractmethod
    async def list_collections(self) -> list[str]: ...

    @abstractmethod
    async def search(self, req: SearchRequest) -> RowBatch: ...

    @abstractmethod
    async def count(self, collection: str, filter_ir: IRNode | None) -> int: ...

    @abstractmethod
    def compile_filter(self, node: IRNode | None) -> object: ...

    @abstractmethod
    async def sample(self, collection: str, n: int) -> list[dict[str, Any]]: ...

    async def introspect_native(self, collection: str | None = None) -> dict[str, Any] | None:
        return None

    async def uses_server_side_embedding(self, collection: str) -> bool:
        """Return whether text queries should omit a client-generated vector."""
        _ = collection
        return False

    async def create_field_index(self, collection: str, path: str, dtype: str) -> None:
        return None

    async def aclose(self) -> None:
        return None
