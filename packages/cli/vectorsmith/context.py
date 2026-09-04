"""Framework-neutral conversion into VectorSmith request identity."""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from vectorsmith_core.api import CallContext


def coerce_call_context(value: object | None) -> CallContext | None:
    if isinstance(value, CallContext):
        return value
    nested = getattr(value, "context", None)
    if nested is not None and nested is not value:
        converted = coerce_call_context(nested)
        if converted is not None:
            return converted
    if not isinstance(value, Mapping):
        return None
    for key in ("vectorsmith_context", "call_context"):
        if key in value:
            converted = coerce_call_context(value[key])
            if converted is not None:
                return converted
    configurable = value.get("configurable")
    if isinstance(configurable, Mapping):
        converted = coerce_call_context(configurable)
        if converted is not None:
            return converted
    metadata = value.get("metadata")
    if isinstance(metadata, Mapping) and "vectorsmith_context" in metadata:
        converted = coerce_call_context(metadata["vectorsmith_context"])
        if converted is not None:
            return converted

    identity_keys = {"principal", "claims", "roles", "tenant_value", "deadline_s", "request_id"}
    if not identity_keys.intersection(value):
        return None
    claims = dict(value.get("claims") or {}) if isinstance(value.get("claims"), Mapping) else {}
    roles = value.get("roles")
    if isinstance(roles, (list, tuple, set)):
        claims.setdefault("roles", [str(role) for role in roles])
    return CallContext(
        request_id=str(value.get("request_id") or uuid.uuid4()),
        deadline_s=float(value.get("deadline_s") or 25.0),
        principal=str(value["principal"]) if value.get("principal") is not None else None,
        claims=claims,
        tenant_value=(
            str(value["tenant_value"]) if value.get("tenant_value") is not None else None
        ),
    )


def fresh_call_context(value: object | None = None) -> CallContext:
    return coerce_call_context(value) or CallContext(request_id=str(uuid.uuid4()))
