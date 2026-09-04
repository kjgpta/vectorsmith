from __future__ import annotations

from pathlib import Path

import yaml

from vectorsmith_cli.authoring_cmd import (
    compare_schema,
    discovery_drafts,
    evaluate_result,
)
from vectorsmith_cli.drafts_cmd import run_approve
from vectorsmith_cli.serve_common import _define_tool
from vectorsmith_core.api import load_project


def _source() -> dict:
    return {
        "tds_version": "2",
        "meta": {"tool_catalog_version": "1.2.3", "deprecated": [{"name": "old_tool"}]},
        "connections": {
            "main": {
                "backend": "qdrant",
                "url": "http://localhost:6333",
                "builtin_defaults": {
                    "collections": ["docs"],
                    "static_filters": [
                        {"path": "tenant", "op": "eq", "value": "acme"}
                    ],
                },
            }
        },
        "tools": [],
    }


def test_discovery_generates_pending_draft_with_supported_ops_and_guardrails() -> None:
    project = load_project(_source(), env={})
    report = {
        "backend": "qdrant",
        "redacted": True,
        "collections": [
            {
                "name": "docs",
                "fields": [
                    {"path": "tenant", "dtype": "keyword"},
                    {"path": "status", "dtype": "keyword", "enum": ["open", "closed"]},
                    {"path": "amount", "dtype": "float"},
                ],
            }
        ],
    }

    result = discovery_drafts(project, report, connection="main")

    assert result["tenant_field_candidates"] == {"docs": ["tenant"]}
    assert len(result["drafts"]) == 1
    draft = result["drafts"][0]
    assert draft["status"] == "pending"
    assert {item["op"] for item in draft["tool"]["parameters"]} <= project.tds.connections[
        "main"
    ].builtin_defaults.model_fields_set | {"eq", "gte"}
    assert any(
        item["path"] == "tenant"
        for item in draft["tool"]["static_filters"]["must"]
    )
    assert not project.tools


def test_eval_invariants_cover_isolation_and_quality() -> None:
    rows = [
        {"_id": "a", "tenant": "acme", "_score": 0.9},
        {"_id": "b", "tenant": "acme", "_score": 0.8},
    ]
    assert (
        evaluate_result(
            rows,
            {
                "exact_rows": 2,
                "row_field_equals": {"tenant": "acme"},
                "forbidden_field_values": {"tenant": ["other"]},
                "min_score": 0.75,
            },
        )
        == []
    )
    assert evaluate_result(rows, {"row_field_equals": {"tenant": "other"}})


def test_schema_drift_reports_add_remove_and_type_changes() -> None:
    checked = {
        "collections": [
            {
                "name": "docs",
                "fields": [
                    {"path": "status", "dtype": "keyword"},
                    {"path": "old", "dtype": "keyword"},
                ],
            }
        ]
    }
    live = {
        "collections": [
            {
                "name": "docs",
                "fields": [
                    {"path": "status", "dtype": "integer"},
                    {"path": "new", "dtype": "boolean"},
                ],
            }
        ]
    }

    drift = compare_schema(checked, live)

    assert drift["has_drift"]
    assert drift["added"][0]["path"] == "new"
    assert drift["removed"][0]["path"] == "old"
    assert drift["type_changed"][0]["path"] == "status"


def test_approval_preserves_comments_and_records_semantic_provenance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    tools = tmp_path / "tools.yaml"
    tools.write_text(
        "# catalog-owner: platform\n"
        + yaml.safe_dump(_source(), sort_keys=False)
    )
    project = load_project(tools)
    _define_tool(
        project,
        {
            "name": "search_docs",
            "description": "Search documents by their approved status and amount.",
            "spec": {
                "name": "search_docs",
                "description": "Search documents by their approved status and amount.",
                "kind": "search",
                "target": {"connection": "main", "collection": "docs"},
                "parameters": [
                    {
                        "name": "status",
                        "path": "status",
                        "dtype": "keyword",
                        "op": "eq",
                    }
                ],
            },
        },
        tmp_path / "tools.drafts.yaml",
    )

    run_approve("search_docs", tools, approver="alice")

    text = tools.read_text()
    active = yaml.safe_load(text)
    stored = yaml.safe_load((tmp_path / "tools.drafts.yaml").read_text())["drafts"][0]
    assert "# catalog-owner: platform" in text
    assert active["meta"]["tool_catalog_version"] == "1.2.4"
    assert active["meta"]["deprecated"] == [{"name": "old_tool"}]
    assert active["tools"][0]["name"] == "search_docs"
    assert stored["provenance"]["approved_by"] == "alice"
    assert stored["catalog_version"] == "1.2.4"


def test_approval_dry_run_does_not_mutate_catalog_or_draft(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    tools = tmp_path / "tools.yaml"
    tools.write_text(yaml.safe_dump(_source(), sort_keys=False))
    drafts = tmp_path / "tools.drafts.yaml"
    drafts.write_text(
        yaml.safe_dump(
            {
                "drafts": [
                    {
                        "status": "pending",
                        "hash": "abc",
                        "tool": {
                            "name": "search_docs",
                            "description": "Search documents by an approved status filter.",
                            "kind": "search",
                            "target": {"connection": "main", "collection": "docs"},
                        },
                    }
                ]
            },
            sort_keys=False,
        )
    )
    before_tools = tools.read_text()
    before_drafts = drafts.read_text()

    run_approve("search_docs", tools, approver="alice", dry_run=True)

    assert tools.read_text() == before_tools
    assert drafts.read_text() == before_drafts
