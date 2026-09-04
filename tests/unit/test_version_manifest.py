from __future__ import annotations

from pathlib import Path

import pytest

from tests.conformance.version_manifest import BACKENDS, load_manifest

pytestmark = pytest.mark.version


def test_manifest_defines_every_backend_and_boundary() -> None:
    manifest = load_manifest()

    assert tuple(manifest.backends) == BACKENDS
    assert manifest.python == "3.12"
    for backend in manifest.backends.values():
        assert backend.version_for("min") == backend.minimum_tested
        assert backend.version_for("pinned") == backend.pinned
        assert backend.version_for("max") == backend.newest_tested
        assert backend.python == ">=3.11"

    assert manifest.backends["weaviate"].minimum == "4.4"
    assert manifest.backends["weaviate"].minimum_tested == "4.4.0"
    assert manifest.backends["qdrant"].minimum_tested == "1.10.1"
    assert manifest.backends["pgvector"].minimum_tested == "3.2.1"
    assert manifest.backends["chroma"].minimum_tested == "1.5.0"
    assert manifest.backends["milvus"].minimum_tested == "2.6.0"


def test_manifest_rejects_missing_backend(tmp_path: Path) -> None:
    manifest = tmp_path / "versions.toml"
    manifest.write_text(
        'schema_version = 1\n[defaults]\npython = "3.12"\n[backends]\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="backends must be exactly"):
        load_manifest(manifest)


def test_boundary_rejects_unknown_name() -> None:
    backend = load_manifest().backends["qdrant"]

    with pytest.raises(ValueError, match="unknown boundary"):
        backend.version_for("latest")
