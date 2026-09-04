"""drafts list/reject and approve."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml as pyyaml
from ruamel.yaml import YAML

from vectorsmith_core.api import draft_tool, load_project, promote_draft


def _drafts_path() -> Path:
    return Path("tools.drafts.yaml")


def run_drafts(action: str, name: str | None) -> None:
    path = _drafts_path()
    data = {"drafts": []}
    if path.exists():
        loaded = pyyaml.safe_load(path.read_text()) or {}
        data["drafts"] = loaded.get("drafts") or []
    if action == "list":
        for d in data["drafts"]:
            tool = d.get("tool") or {}
            print(f"{d.get('status', 'pending'):10} {tool.get('name', '?')}", file=sys.stderr)
        return
    if action == "reject" and name:
        for d in data["drafts"]:
            if (d.get("tool") or {}).get("name") == name:
                d["status"] = "rejected"
        path.write_text(pyyaml.safe_dump(data, sort_keys=False))
        print(f"rejected {name}", file=sys.stderr)
        return
    print("usage: drafts list | reject NAME", file=sys.stderr)
    raise SystemExit(2)


def _next_catalog_version(value: object) -> str:
    current = str(value or "0")
    parts = current.split(".")
    if all(part.isdigit() for part in parts):
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    return "1"


def semantic_approval_diff(
    name: str,
    *,
    before_version: object,
    after_version: str,
    tool: dict[str, object],
    provenance: dict[str, object],
) -> dict[str, object]:
    static = tool.get("static_filters")
    return {
        "action": "approve_read_only_tool",
        "tool": name,
        "kind": tool.get("kind"),
        "target": tool.get("target"),
        "parameters": tool.get("parameters") or [],
        "guardrails": static or {"must": [], "must_not": []},
        "catalog_version": {
            "before": before_version,
            "after": after_version,
        },
        "provenance": provenance,
    }


def run_approve(
    name: str,
    tools_file: Path,
    *,
    approver: str | None = None,
    dry_run: bool = False,
) -> None:
    path = _drafts_path()
    if not path.exists():
        print("no tools.drafts.yaml", file=sys.stderr)
        raise SystemExit(2)
    data = pyyaml.safe_load(path.read_text()) or {}
    drafts = data.get("drafts") or []
    match = next((d for d in drafts if (d.get("tool") or {}).get("name") == name), None)
    if match is None:
        print(f"draft {name} not found", file=sys.stderr)
        raise SystemExit(2)
    project = load_project(tools_file)
    from vectorsmith_core.api import ToolDraft
    from vectorsmith_core.tds.models import ToolSpec

    spec = ToolSpec.model_validate(match["tool"])
    draft = ToolDraft(spec=spec, validator_issues=[], provenance=match)
    promoted = promote_draft(draft, project)
    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    raw = yaml_rt.load(tools_file.read_text())
    raw.setdefault("meta", {})
    before_version = raw["meta"].get("tool_catalog_version")
    after_version = _next_catalog_version(before_version)
    tool = promoted.model_dump(exclude_none=True)
    provenance = dict(match.get("provenance") or {})
    provenance.update(
        {
            "hash": match.get("hash") or provenance.get("hash"),
            "approved_by": approver or os.getenv("USER") or "local-user",
            "approved_at": datetime.now(UTC).isoformat(),
        }
    )
    diff = semantic_approval_diff(
        name,
        before_version=before_version,
        after_version=after_version,
        tool=tool,
        provenance=provenance,
    )
    print(json.dumps(diff, indent=2, default=str), file=sys.stderr)
    if dry_run:
        print("dry-run: active catalog and draft status unchanged", file=sys.stderr)
        return
    raw.setdefault("tools", []).append(tool)
    raw["meta"]["tool_catalog_version"] = after_version
    with tools_file.open("w") as stream:
        yaml_rt.dump(raw, stream)
    match["status"] = "approved"
    match["provenance"] = provenance
    match["catalog_version"] = after_version
    path.write_text(pyyaml.safe_dump(data, sort_keys=False))
    print(f"Approved {name}. Toggle the connector in Claude to load it.", file=sys.stderr)


# draft_tool imported for define_tool serve path
_ = draft_tool
