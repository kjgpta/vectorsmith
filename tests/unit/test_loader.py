"""T5: loader — env interpolation, extras, secret lint."""

from __future__ import annotations

from pathlib import Path

import pytest

from vectorsmith_core.errors import MissingEnvError
from vectorsmith_core.tds.loader import looks_like_secret, parse_tds

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CORPUS = FIXTURES / "secret_lint_corpus.txt"
CLEAN = FIXTURES / "clean_env_refs.yaml"


def _minimal(url: str = "${QDRANT_URL}") -> dict:
    return {
        "tds_version": "1",
        "connections": {"main": {"backend": "qdrant", "url": url}},
        "tools": [
            {
                "name": "search_invoices",
                "description": "Search invoices by client status and due date.",
                "target": {"connection": "main", "collection": "invoices"},
            }
        ],
    }


def test_all_missing_env_at_once() -> None:
    data = {
        "tds_version": "1",
        "connections": {
            "main": {
                "backend": "qdrant",
                "url": "${QDRANT_URL}",
                "api_key": "${QDRANT_API_KEY}",
            }
        },
        "tools": _minimal()["tools"],
    }
    with pytest.raises(MissingEnvError) as ei:
        parse_tds(data, env={})
    assert set(ei.value.vars) == {"QDRANT_URL", "QDRANT_API_KEY"}


def test_env_default_and_override() -> None:
    data = _minimal("${QDRANT_URL:-http://localhost:6333}")
    tds, vb1003, extras, secrets = parse_tds(data, env={})
    assert tds.connections["main"].url == "http://localhost:6333"  # type: ignore[union-attr]
    assert not vb1003
    assert not secrets


def test_env_ref_outside_connections_is_vb1003() -> None:
    data = _minimal()
    data["defaults"] = {"embedding": "${MODEL}"}
    _tds, vb1003, _e, _s = parse_tds(data, env={"QDRANT_URL": "http://q"})
    assert any("defaults" in p for p in vb1003)


def test_unknown_key_walk() -> None:
    data = _minimal()
    data["future_flag"] = True
    _tds, _v, extras, _s = parse_tds(data, env={"QDRANT_URL": "http://q"})
    keys = [k for _p, k in extras]
    assert "future_flag" in keys


def test_secret_corpus_hit_rate() -> None:
    lines = [
        ln.strip()
        for ln in CORPUS.read_text().splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    assert len(lines) >= 50
    hits = sum(1 for ln in lines if looks_like_secret(ln))
    assert hits >= 48


def test_clean_env_refs_no_false_positive() -> None:
    _tds, _v, _e, secrets = parse_tds(CLEAN, env={"QDRANT_URL": "http://q", "QDRANT_API_KEY": "x"})
    assert secrets == []


def test_secret_lint_ignores_noncredential_connection_metadata() -> None:
    data = _minimal("http://localhost:6333")
    data["connections"]["main"]["builtin_defaults"] = {
        "collections": ["VectorsmithConformance"],
    }

    _tds, _v, _e, secrets = parse_tds(data, env={})

    assert secrets == []


def test_secret_lint_still_checks_credential_fields() -> None:
    data = _minimal("http://localhost:6333")
    data["connections"]["main"]["api_key"] = "sk-" + ("a9" * 24)

    _tds, _v, _e, secrets = parse_tds(data, env={})

    assert secrets == ["connections.main.api_key"]
