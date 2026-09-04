"""Parse and validate conformance client version boundaries."""

from __future__ import annotations

import argparse
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BOUNDARIES = ("min", "pinned", "max")
BACKENDS = ("qdrant", "pgvector", "chroma", "pinecone", "weaviate", "milvus")
MANIFEST = Path(__file__).with_name("versions.toml")


@dataclass(frozen=True)
class VersionBoundary:
    backend: str
    service: str
    server: str
    client: str
    minimum: str
    minimum_tested: str
    pinned: str
    newest_tested: str
    python: str

    def version_for(self, boundary: str) -> str:
        if boundary not in BOUNDARIES:
            raise ValueError(f"unknown boundary {boundary!r}")
        return {
            "min": self.minimum_tested,
            "pinned": self.pinned,
            "max": self.newest_tested,
        }[boundary]


@dataclass(frozen=True)
class VersionManifest:
    python: str
    backends: dict[str, VersionBoundary]


def load_manifest(path: Path = MANIFEST) -> VersionManifest:
    with path.open("rb") as stream:
        raw = tomllib.load(stream)

    if raw.get("schema_version") != 1:
        raise ValueError("versions.toml must use schema_version = 1")
    python = _required_string(raw.get("defaults", {}), "python", "defaults")
    backend_data = raw.get("backends")
    if not isinstance(backend_data, dict):
        raise ValueError("versions.toml must define [backends]")
    if set(backend_data) != set(BACKENDS):
        raise ValueError(f"versions.toml backends must be exactly {BACKENDS!r}")

    backends: dict[str, VersionBoundary] = {}
    for name in BACKENDS:
        values = backend_data[name]
        if not isinstance(values, dict):
            raise ValueError(f"backends.{name} must be a table")
        required = (
            "service",
            "server",
            "client",
            "minimum",
            "minimum_tested",
            "pinned",
            "newest_tested",
            "python",
        )
        parsed = {key: _required_string(values, key, f"backends.{name}") for key in required}
        backends[name] = VersionBoundary(backend=name, **parsed)

    return VersionManifest(python=python, backends=backends)


def _required_string(values: dict[str, Any], key: str, table: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{table}.{key} must be a non-empty string")
    return value


def _resolve(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest)
    boundary = manifest.backends[args.backend]
    values = {
        "backend": boundary.backend,
        "boundary": args.boundary,
        "client": boundary.client,
        "client_version": boundary.version_for(args.boundary),
        "declared_minimum": boundary.minimum,
        "python": manifest.python,
        "python_constraint": boundary.python,
        "server": boundary.server,
        "service": boundary.service,
    }
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(values, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.github_output is None and args.json_output is None:
        print(json.dumps(values, sort_keys=True))
    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as stream:
            for key, value in values.items():
                stream.write(f"{key}={value}\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--backend", choices=BACKENDS, required=True)
    parser.add_argument("--boundary", choices=BOUNDARIES, required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--json-output", type=Path)
    return _resolve(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
