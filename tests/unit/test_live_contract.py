"""validate --live embedding dim + payload-path drift (no store)."""

from __future__ import annotations

from vectorsmith_core.api import load_project
from vectorsmith_core.compilepkg.validator import embedding_dim, live_contract_issues


def _project(*, embedding: str | None = None, extra_path: str = "client_name"):
    tool: dict = {
        "name": "search_invoices",
        "description": "Search invoices by client status and due date for billing.",
        "target": {"connection": "main", "collection": "invoices"},
        "query": {"param": "query"},
        "static_filters": [{"path": "tenant", "op": "eq", "value": "acme"}],
        "parameters": [
            {"name": "client", "path": extra_path, "dtype": "keyword", "op": "eq"}
        ],
        "output": {"fields": ["invoice_id", extra_path]},
    }
    if embedding:
        tool["query"]["embedding"] = embedding
    return load_project(
        {
            "tds_version": "1",
            "connections": {"main": {"backend": "qdrant", "url": "http://localhost:6333"}},
            "tools": [tool],
        },
        env={"QDRANT_URL": "http://localhost:6333"},
    )


def _plans(project):
    return {n: t.plan for n, t in project.tools.items() if t.plan is not None}


def test_embedding_dim_known_models() -> None:
    assert embedding_dim("fastembed/BAAI/bge-small-en-v1.5") == 384
    assert embedding_dim("totally-unknown/model") is None


def test_vb2017_dim_mismatch() -> None:
    project = _project()
    issues = live_contract_issues(
        project.tds,
        _plans(project),
        {"main:invoices": {"dim": 768, "fields": ["tenant", "client_name", "invoice_id"]}},
    )
    assert any(i.code == "VB2017" and i.severity == "error" for i in issues)


def test_vb2018_unknown_model() -> None:
    project = _project(embedding="vendor/mystery-embed-v9")
    issues = live_contract_issues(
        project.tds,
        _plans(project),
        {"main:invoices": {"dim": 384, "fields": ["tenant", "client_name", "invoice_id"]}},
    )
    assert any(i.code == "VB2018" and i.severity == "warning" for i in issues)
    assert not any(i.code == "VB2017" for i in issues)


def test_matching_dim_is_silent() -> None:
    project = _project()
    issues = live_contract_issues(
        project.tds,
        _plans(project),
        {"main:invoices": {"dim": 384, "fields": ["tenant", "client_name", "invoice_id"]}},
    )
    assert not any(i.code in {"VB2017", "VB2018", "VB4004"} for i in issues)


def test_vb4004_payload_path_drift() -> None:
    project = _project(extra_path="renamed_client")
    issues = live_contract_issues(
        project.tds,
        _plans(project),
        {"main:invoices": {"dim": 384, "fields": ["tenant", "invoice_id"]}},
    )
    codes = [i.code for i in issues if i.severity == "warning"]
    assert "VB4004" in codes
    assert any("renamed_client" in i.message for i in issues)


def test_vb2026_missing_explicit_filter_index() -> None:
    project = _project()
    issues = live_contract_issues(
        project.tds,
        _plans(project),
        {
            "main:invoices": {
                "dim": 384,
                "fields": ["tenant", "client_name", "invoice_id"],
                "indexed_paths": {"tenant": {"type": "keyword"}},
            }
        },
    )

    missing = [issue for issue in issues if issue.code == "VB2026"]
    assert [(issue.path, issue.severity) for issue in missing] == [("client_name", "error")]


def test_explicit_index_check_skips_unavailable_native_data() -> None:
    project = _project()
    issues = live_contract_issues(
        project.tds,
        _plans(project),
        {"main:invoices": {"dim": 384, "fields": ["tenant", "client_name", "invoice_id"]}},
    )

    assert not any(issue.code == "VB2026" for issue in issues)
