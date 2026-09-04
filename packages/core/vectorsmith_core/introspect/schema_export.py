"""schema.json export (metadata only)."""

from __future__ import annotations

import json
from typing import Any

SCHEMA_V1 = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["connection", "backend", "collections"],
    "properties": {
        "connection": {"type": "string"},
        "backend": {"type": "string"},
        "redacted": {"type": "boolean"},
        "collections": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "sampled_n": {"type": "integer"},
                    "introspection": {"type": "string"},
                    "vector": {
                        "type": "object",
                        "properties": {
                            "sparse": {"type": "boolean"},
                            "dim": {"type": ["integer", "null"]},
                        },
                    },
                    "fields": {"type": "array"},
                },
            },
        },
    },
}


def to_schema_json(report: dict[str, Any]) -> dict[str, Any]:
    """Drop records/ids/vectors/creds and self-validate the envelope."""
    cleaned: dict[str, Any] = {
        "connection": report.get("connection"),
        "backend": report.get("backend"),
        "redacted": bool(report.get("redacted")),
        "collections": [],
    }
    for col in report.get("collections") or []:
        cleaned["collections"].append(
            {
                "name": col.get("name"),
                "sampled_n": col.get("sampled_n", 0),
                "introspection": col.get("introspection", "none"),
                "vector": {
                    "sparse": bool((col.get("vector") or {}).get("sparse")),
                    "dim": (col.get("vector") or {}).get("dim"),
                },
                "fields": col.get("fields") or [],
                "native": col.get("native"),
            }
        )
    validate_schema(cleaned)
    return cleaned


def validate_schema(report: dict[str, Any]) -> None:
    import jsonschema

    jsonschema.validate(report, SCHEMA_V1)


def dumps(report: dict[str, Any]) -> str:
    return json.dumps(to_schema_json(report), indent=2, default=str)
