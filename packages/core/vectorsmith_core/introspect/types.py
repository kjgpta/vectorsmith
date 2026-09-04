"""Normalized native and sampled introspection contracts."""

from __future__ import annotations

from typing import Any, TypedDict


class NativeField(TypedDict, total=False):
    path: str
    dtype: str
    nullable: bool
    indexed: bool
    provenance: str


class NativeInfo(TypedDict, total=False):
    dim: int | None
    sparse: bool
    fields: list[NativeField]
    indexed_paths: dict[str, str]
    vectorizer: str | None
    self_provided: bool | None
    provenance: str


def merge_fields(
    native_fields: list[dict[str, Any]],
    sampled_fields: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge field evidence, preferring native dtypes and sampled statistics."""
    merged: dict[str, dict[str, Any]] = {}
    for field in sampled_fields:
        path = str(field.get("path") or "")
        if path:
            merged[path] = {**field, "provenance": "sample"}
    for field in native_fields:
        path = str(field.get("path") or "")
        if not path:
            continue
        sampled = merged.get(path, {})
        dtype = field.get("dtype")
        merged[path] = {
            **sampled,
            **field,
            "dtype": dtype if dtype not in {None, "unknown"} else sampled.get("dtype", "unknown"),
            "provenance": "native",
        }
    return [merged[path] for path in sorted(merged)]
