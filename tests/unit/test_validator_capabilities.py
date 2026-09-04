from __future__ import annotations

from vectorsmith_core.api import load_project
from vectorsmith_core.compilepkg.validator import validate


def _connection(backend: str) -> dict[str, object]:
    if backend == "qdrant":
        return {"backend": backend, "url": "http://localhost:6333"}
    if backend == "chroma":
        return {"backend": backend, "url": "http://localhost:8000"}
    if backend == "pinecone":
        return {"backend": backend, "host": "http://localhost:5081", "api_key": "local"}
    raise AssertionError(f"unsupported test backend: {backend}")


def _project(backend: str, tool: dict[str, object], **connections: dict[str, object]):
    return load_project(
        {
            "tds_version": "2",
            "connections": {"main": _connection(backend), **connections},
            "tools": [tool],
        },
        env={},
    )


def test_parameter_and_both_static_filter_branches_gate_nested_paths() -> None:
    project = _project(
        "chroma",
        {
            "name": "search_invoices",
            "description": "Search invoices using nested customer metadata and tags.",
            "target": {"connection": "main", "collection": "invoices"},
            "parameters": [
                {
                    "name": "region",
                    "path": "customer.region",
                    "dtype": "keyword",
                    "op": "eq",
                },
                {"name": "tags", "path": "tags", "dtype": "keyword[]", "op": "in"},
                {"name": "present", "path": "status", "dtype": "keyword", "op": "exists"},
            ],
            "static_filters": {
                "must": [{"path": "tenant.id", "op": "eq", "value": "acme"}],
                "must_not": [{"path": "flags.archived", "op": "eq", "value": True}],
            },
        },
    )

    capability_errors = [issue for issue in project.issues if issue.code == "VB2004"]
    assert {issue.path for issue in capability_errors} >= {
        "customer.region",
        "tags",
        "status",
        "tenant.id",
        "flags.archived",
    }
    assert any("array filters" in issue.message for issue in capability_errors)
    assert any("op 'exists'" in issue.message for issue in capability_errors)


def test_builtin_default_static_filters_gate_nested_paths() -> None:
    connection = _connection("chroma")
    connection["builtin_defaults"] = {
        "static_filters": {
            "must": [{"path": "tenant.id", "op": "eq", "value": "acme"}],
            "must_not": [{"path": "flags.archived", "op": "eq", "value": True}],
        }
    }
    project = load_project(
        {"tds_version": "2", "connections": {"main": connection}, "tools": []},
        env={},
    )

    paths = {issue.path for issue in project.issues if issue.code == "VB2004"}
    assert paths == {
        "connections.main.builtin_defaults.static_filters.must.tenant.id",
        "connections.main.builtin_defaults.static_filters.must_not.flags.archived",
    }


def test_scroll_and_filtered_count_use_backend_capabilities() -> None:
    scroll = _project(
        "pinecone",
        {
            "name": "scroll_invoices",
            "description": "Scroll through invoices for an offline reconciliation process.",
            "kind": "scroll",
            "target": {"connection": "main", "collection": "invoices"},
        },
    )
    assert any(
        issue.code == "VB2004" and "does not support scroll" in issue.message
        for issue in scroll.issues
    )

    count = _project(
        "pinecone",
        {
            "name": "count_invoices",
            "description": "Count invoices restricted to the current customer tenant.",
            "kind": "count",
            "target": {"connection": "main", "collection": "invoices"},
            "static_filters": [{"path": "tenant", "op": "eq", "value": "acme"}],
        },
    )
    assert any(
        issue.code == "VB2004" and "filtered count" in issue.message
        for issue in count.issues
    )


def test_directory_resolve_checks_its_explicit_connection() -> None:
    project = _project(
        "qdrant",
        {
            "name": "search_invoices",
            "description": "Search invoices after resolving a customer directory value.",
            "target": {"connection": "main", "collection": "invoices"},
            "parameters": [
                {
                    "name": "customer",
                    "path": "customer",
                    "resolve": {
                        "kind": "directory",
                        "connection": "directory",
                        "collection": "customers",
                        "field": "name",
                    },
                }
            ],
        },
        directory=_connection("pinecone"),
    )

    assert any(issue.code == "VB4021" and issue.path == "customer" for issue in project.issues)


def test_hybrid_capability_and_pipeline_live_sparse_check() -> None:
    unsupported = _project(
        "chroma",
        {
            "name": "search_invoices",
            "description": "Search invoices with combined dense and sparse retrieval.",
            "target": {"connection": "main", "collection": "invoices"},
            "query": {"mode": "hybrid"},
        },
    )
    assert any(issue.code == "VB2012" for issue in unsupported.issues)

    pipeline = _project(
        "qdrant",
        {
            "name": "search_invoice_pipeline",
            "description": "Search invoices through a hybrid retrieval pipeline.",
            "kind": "pipeline",
            "steps": [
                {
                    "retrieve": {
                        "target": {"connection": "main", "collection": "invoices"},
                        "query": {"mode": "hybrid"},
                    }
                }
            ],
        },
    )
    issues = validate(pipeline.tds, live_sparse={"main:invoices": False})
    assert any(issue.code == "VB2013" and issue.severity == "error" for issue in issues)
