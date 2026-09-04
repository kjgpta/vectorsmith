"""TDS loading: safe YAML, env interpolation, extra-key walk, secret lint."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from vectorsmith_core.errors import MissingEnvError, TDSValidationError
from vectorsmith_core.tds.models import TDSFile

MAX_BYTES = 1_000_000
MAX_ANCHORS = 100
MAX_DEPTH = 20
_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
_SECRET_PREFIXES = ("sk-", "pcsk_", "eyJ", "AKIA", "SG.", "dapi", "sl.", "BEGIN PRIVATE")
_PASSWORD_RE = re.compile(r"(?:password|pwd)=([^;\s]+)", re.IGNORECASE)
_USERINFO_RE = re.compile(r"://[^/\s:]+:[^/\s@]+@")


class YamlSafetyError(TDSValidationError):
    def __init__(self, message: str) -> None:
        super().__init__([], detail=message)


def _safe_load(text: str) -> object:
    class _Loader(yaml.SafeLoader):
        pass

    anchors = 0

    def _compose_node(
        self: yaml.SafeLoader, parent: yaml.nodes.Node | None, index: int
    ) -> yaml.nodes.Node | None:
        nonlocal anchors
        node = yaml.SafeLoader.compose_node(self, parent, index)
        if getattr(node, "anchor", None):
            anchors += 1
            if anchors > MAX_ANCHORS:
                raise YamlSafetyError("YAML exceeds 100 anchors")
        return node

    _Loader.compose_node = _compose_node  # type: ignore[method-assign, assignment]
    data = yaml.load(text, Loader=_Loader)  # noqa: S506 — SafeLoader subclass
    _assert_depth(data, 0)
    return data


def _assert_depth(obj: object, depth: int) -> None:
    if depth > MAX_DEPTH:
        raise YamlSafetyError("YAML exceeds depth 20")
    if isinstance(obj, dict):
        for v in obj.values():
            _assert_depth(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            _assert_depth(v, depth + 1)


def _interp_allowed(path: str) -> bool:
    if path == "connections" or path.startswith("connections."):
        return True
    if path == "defaults.embedding.config" or path.startswith("defaults.embedding.config."):
        return True
    if ".query.embedding.config" in path:
        return True
    if ".query.expand.config" in path:
        return True
    if ".rerank.config" in path:
        return True
    if path == "observability.tracing.endpoint":
        return True
    if path == "security.auth" or path.startswith("security.auth."):
        return True
    if path == "security.rate_limit.redis_url":
        return True
    if path.startswith("observability.audit.") and path.endswith((".url", ".path")):
        return True
    return False


def interpolate_connections(
    data: dict[str, Any],
    env: Mapping[str, str] | None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Replace ``${VAR}`` under ``connections`` and embedding ``config`` blocks.

    Returns ``(data, missing_env_names, vb1003_paths)``.
    """
    env = env if env is not None else {}
    missing: list[str] = []
    vb1003: list[str] = []

    def _sub(value: str) -> str:
        def repl(m: re.Match[str]) -> str:
            name, default = m.group(1), m.group(2)
            if name in env:
                return env[name]
            if default is not None:
                return default
            missing.append(name)
            return m.group(0)

        return _ENV_RE.sub(repl, value)

    def walk(obj: Any, path: str) -> Any:
        allow = _interp_allowed(path)
        if isinstance(obj, dict):
            return {
                k: walk(v, f"{path}.{k}" if path else k)
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [walk(v, f"{path}[{i}]") for i, v in enumerate(obj)]
        if isinstance(obj, str):
            if _ENV_RE.search(obj) and not allow:
                vb1003.append(path)
                return obj
            return _sub(obj) if allow else obj
        return obj

    out = walk(data, "")
    if not isinstance(out, dict):
        return data, missing, vb1003
    return out, missing, vb1003


def walk_extras(model: object, path: str = "") -> list[tuple[str, str]]:
    """Collect (path, key) for unknown fields (``model_extra``)."""
    found: list[tuple[str, str]] = []
    extra = getattr(model, "model_extra", None)
    if extra:
        for k in extra:
            found.append((path, str(k)))
    cls = type(model)
    fields = getattr(cls, "model_fields", {})
    for name in fields:
        child = getattr(model, name, None)
        child_path = f"{path}.{name}" if path else name
        if isinstance(child, list):
            for i, item in enumerate(child):
                found.extend(walk_extras(item, f"{child_path}[{i}]"))
        elif isinstance(child, dict):
            for k, item in child.items():
                found.extend(walk_extras(item, f"{child_path}.{k}"))
        else:
            found.extend(walk_extras(child, child_path))
    return found


def _shannon(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    return -sum((n / len(s)) * math.log2(n / len(s)) for n in freq.values())


def looks_like_secret(value: str) -> bool:
    """True when a literal connection value looks like an inline secret."""
    if value.startswith("${") and "}" in value:
        return False
    if _ENV_RE.fullmatch(value.strip()):
        return False
    pw = _PASSWORD_RE.search(value)
    if pw and not pw.group(1).startswith("${"):
        return True
    if _USERINFO_RE.search(value):
        return True
    if len(value) < 16:
        return False
    if any(value.startswith(p) or p in value for p in _SECRET_PREFIXES):
        return True
    return _shannon(value) > 3.5


def lint_secrets(connections: Mapping[str, Any]) -> list[str]:
    hits: list[str] = []
    sensitive = {"api_key", "auth_token", "token", "password", "dsn"}

    def walk(obj: Any, path: str, *, inspect_value: bool = False) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{path}.{k}", inspect_value=inspect_value or k in sensitive)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]", inspect_value=inspect_value)
        elif inspect_value and isinstance(obj, str) and looks_like_secret(obj):
            hits.append(path)

    walk(connections, "connections")
    return hits


def lint_embedding_secrets(data: Mapping[str, Any]) -> list[str]:
    hits: list[str] = []

    def walk(obj: Any, path: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")
        elif isinstance(obj, str) and looks_like_secret(obj):
            hits.append(path)

    defaults = data.get("defaults")
    if isinstance(defaults, dict):
        emb = defaults.get("embedding")
        if isinstance(emb, dict):
            walk(emb.get("config") or {}, "defaults.embedding.config")
    tools = data.get("tools")
    if isinstance(tools, list):
        for i, tool in enumerate(tools):
            if not isinstance(tool, dict):
                continue
            query = tool.get("query")
            if isinstance(query, dict) and isinstance(query.get("embedding"), dict):
                walk(
                    query["embedding"].get("config") or {},
                    f"tools[{i}].query.embedding.config",
                )
            for j, step in enumerate(tool.get("steps") or []):
                if not isinstance(step, dict):
                    continue
                retrieve = step.get("retrieve")
                if not isinstance(retrieve, dict):
                    continue
                rq = retrieve.get("query")
                if isinstance(rq, dict) and isinstance(rq.get("embedding"), dict):
                    walk(
                        rq["embedding"].get("config") or {},
                        f"tools[{i}].steps[{j}].retrieve.query.embedding.config",
                    )
    return hits


def read_source(source: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(source, dict):
        return source
    path = Path(source)
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise YamlSafetyError("TDS file exceeds 1MB")
    loaded = _safe_load(raw.decode("utf-8"))
    if not isinstance(loaded, dict):
        raise YamlSafetyError("TDS root must be a mapping")
    return loaded


def parse_tds(
    source: str | Path | dict[str, Any],
    *,
    env: Mapping[str, str] | None = None,
    interpolate: bool = True,
) -> tuple[TDSFile, list[str], list[tuple[str, str]], list[str]]:
    """Return (tds, missing_env_or_vb1003, extras, secret_paths).

    Env interpolation is applied for pydantic parsing; secret lint runs on the
    pre-interpolation connections block so ``${VAR}`` forms stay clean.
    """
    data = read_source(source)
    secret_hits = lint_secrets(data.get("connections") or {})
    secret_hits.extend(lint_embedding_secrets(data))
    vb1003: list[str] = []
    if interpolate:
        data, missing, vb1003 = interpolate_connections(data, env)
        if missing:
            raise MissingEnvError(sorted(set(missing)))
    tds = TDSFile.model_validate(data)
    extras = walk_extras(tds)
    return tds, vb1003, extras, secret_hits
