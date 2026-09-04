"""Experimental local contract discovery, evaluation, and schema drift."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from vectorsmith.runtime import connect
from vectorsmith_cli.validate_cmd import _load_env
from vectorsmith_core.adapters.capabilities import CAPS_BY_BACKEND
from vectorsmith_core.api import draft_tool, load_project
from vectorsmith_core.execute.engine import Engine
from vectorsmith_core.security.credentials import build_credential_resolver

_TENANT_RE = re.compile(
    r"^(tenant|tenant_id|org|org_id|organization_id|account_id|workspace_id|customer_id)$",
    re.IGNORECASE,
)


def _load_checked(path: Path) -> Any:
    value = yaml.safe_load(path.read_text())
    if value is None:
        raise ValueError(f"{path} is empty")
    return value


async def _introspect(
    tools: Path,
    *,
    connection: str,
    collections: list[str] | None,
    env: dict[str, str],
) -> dict[str, Any]:
    project = load_project(tools, env=env)
    errors = [issue for issue in project.issues if issue.severity == "error"]
    if errors:
        raise ValueError("; ".join(f"{item.code}: {item.message}" for item in errors))
    engine = Engine(project, credential_resolver=build_credential_resolver(env))
    try:
        return await engine.introspect(
            connection,
            collections=collections,
            redact_examples=True,
        )
    finally:
        await engine.aclose()


def _recommended_op(dtype: str, supported: frozenset[str]) -> str | None:
    candidates = {
        "keyword": ("eq", "in"),
        "integer": ("gte", "eq"),
        "float": ("gte", "eq"),
        "datetime": ("gte", "eq"),
        "boolean": ("eq",),
        "keyword[]": ("in",),
    }.get(dtype, ())
    return next((operator for operator in candidates if operator in supported), None)


def discovery_drafts(
    project: Any,
    report: Mapping[str, Any],
    *,
    connection: str,
) -> dict[str, Any]:
    backend = str(report.get("backend") or "")
    caps = CAPS_BY_BACKEND[backend]
    blocks: list[dict[str, Any]] = []
    tenant_candidates: dict[str, list[str]] = {}
    for collection in report.get("collections") or []:
        name = str(collection.get("name") or "")
        fields = list(collection.get("fields") or [])
        tenant_candidates[name] = [
            str(field.get("path"))
            for field in fields
            if _TENANT_RE.match(str(field.get("path") or ""))
        ]
        parameters: list[dict[str, Any]] = []
        for field in fields:
            path = str(field.get("path") or "")
            if not path or path.startswith("_") or _TENANT_RE.match(path):
                continue
            dtype = str(field.get("dtype") or "unknown")
            operator = _recommended_op(dtype, caps.ops)
            if operator is None:
                continue
            parameter: dict[str, Any] = {
                "name": re.sub(r"[^a-zA-Z0-9_]", "_", path).lower(),
                "path": path,
                "dtype": dtype,
                "op": operator,
                "required": False,
                "description": f"Filter by {path}",
            }
            enum = field.get("enum")
            if operator in {"eq", "in"} and isinstance(enum, list) and enum:
                parameter["enum"] = enum
            parameters.append(parameter)
            if len(parameters) == 8:
                break
        proposal = {
            "name": f"search_{re.sub(r'[^a-zA-Z0-9_]', '_', name).lower()}",
            "description": f"Search {name} with schema-backed filters and enforced guardrails.",
            "kind": "search",
            "target": {"connection": connection, "collection": name},
            "parameters": parameters,
        }
        draft = draft_tool(
            project,
            {
                "created_by": "vectorsmith discover",
                "connection": connection,
                "collection": name,
                "backend": backend,
            },
            proposal,
        )
        blocks.append(
            {
                "status": "pending",
                "hash": draft.provenance.get("hash"),
                "provenance": draft.provenance,
                "tool": json.loads(draft.spec.model_dump_json(exclude_none=True)),
                "issues": [issue.model_dump() for issue in draft.validator_issues],
            }
        )
    return {
        "experimental": True,
        "source": {
            "connection": connection,
            "backend": backend,
            "redacted": bool(report.get("redacted")),
        },
        "tenant_field_candidates": tenant_candidates,
        "drafts": blocks,
    }


def run_discover(
    tools: Path,
    *,
    connection: str,
    collections: str | None,
    out: Path,
    env_file: Path | None,
    experimental: bool,
) -> int:
    if not experimental:
        print("discover is experimental; pass --experimental", file=sys.stderr)
        return 2
    env = _load_env(env_file)
    project = load_project(tools, env=env)
    try:
        report = asyncio.run(
            _introspect(
                tools,
                connection=connection,
                collections=collections.split(",") if collections else None,
                env=env,
            )
        )
        result = discovery_drafts(project, report, connection=connection)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 3
    out.write_text(yaml.safe_dump(result, sort_keys=False))
    print(f"wrote pending discovery drafts to {out}; active catalog unchanged", file=sys.stderr)
    return 0


def evaluate_result(
    rows: list[dict[str, Any]],
    expected: Mapping[str, Any],
) -> list[str]:
    failures: list[str] = []
    if "exact_rows" in expected and len(rows) != int(expected["exact_rows"]):
        failures.append(f"expected exactly {expected['exact_rows']} rows, got {len(rows)}")
    if "min_rows" in expected and len(rows) < int(expected["min_rows"]):
        failures.append(f"expected at least {expected['min_rows']} rows, got {len(rows)}")
    if "max_rows" in expected and len(rows) > int(expected["max_rows"]):
        failures.append(f"expected at most {expected['max_rows']} rows, got {len(rows)}")
    equals = expected.get("row_field_equals") or {}
    if isinstance(equals, Mapping):
        for path, value in equals.items():
            if any(row.get(str(path)) != value for row in rows):
                failures.append(f"not every row has {path}={value!r}")
    forbidden = expected.get("forbidden_field_values") or {}
    if isinstance(forbidden, Mapping):
        for path, values in forbidden.items():
            blocked = set(values if isinstance(values, list) else [values])
            if any(row.get(str(path)) in blocked for row in rows):
                failures.append(f"forbidden {path} value returned")
    if "min_score" in expected:
        threshold = float(expected["min_score"])
        if any(
            not isinstance(row.get("_score"), (int, float))
            or row["_score"] < threshold
            for row in rows
        ):
            failures.append(f"row score below {threshold}")
    return failures


async def _run_eval_async(
    tools: Path,
    scenarios: list[dict[str, Any]],
    env: dict[str, str],
) -> list[dict[str, Any]]:
    bound = connect(tools, env=env)
    results: list[dict[str, Any]] = []
    try:
        for index, scenario in enumerate(scenarios):
            call = scenario.get("call") or {}
            name = str(call.get("tool") or "")
            arguments = dict(call.get("arguments") or {})
            failures: list[str] = []
            expected_tool = scenario.get("expected_tool")
            if expected_tool is not None and name != expected_tool:
                failures.append(f"selected {name!r}, expected {expected_tool!r}")
            expected_arguments = scenario.get("expected_arguments")
            if isinstance(expected_arguments, Mapping) and arguments != dict(expected_arguments):
                failures.append("call arguments do not match expected_arguments")
            try:
                result = await bound.call(name, arguments)
                rows = list(result.get("rows") or [])
                failures.extend(evaluate_result(rows, scenario.get("expect") or {}))
            except Exception as exc:
                rows = []
                failures.append(f"execution failed: {exc}")
            results.append(
                {
                    "name": scenario.get("name") or f"scenario-{index + 1}",
                    "request": scenario.get("request"),
                    "tool": name,
                    "arguments": arguments,
                    "passed": not failures,
                    "failures": failures,
                    "row_count": len(rows),
                }
            )
    finally:
        await bound.aclose()
    return results


def run_eval(
    tools: Path,
    scenarios_file: Path,
    *,
    out: Path,
    env_file: Path | None,
    experimental: bool,
) -> int:
    if not experimental:
        print("eval is experimental; pass --experimental", file=sys.stderr)
        return 2
    source = _load_checked(scenarios_file)
    scenarios = source.get("scenarios") if isinstance(source, Mapping) else None
    if not isinstance(scenarios, list):
        print("scenario file needs a scenarios list", file=sys.stderr)
        return 2
    results = asyncio.run(_run_eval_async(tools, scenarios, _load_env(env_file)))
    report = {
        "experimental": True,
        "scenario_file": str(scenarios_file),
        "passed": sum(bool(item["passed"]) for item in results),
        "failed": sum(not item["passed"] for item in results),
        "results": results,
    }
    out.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(f"wrote {out}", file=sys.stderr)
    return 1 if report["failed"] else 0


def compare_schema(
    checked: Mapping[str, Any],
    live: Mapping[str, Any],
) -> dict[str, Any]:
    def fields(report: Mapping[str, Any]) -> dict[tuple[str, str], str]:
        output: dict[tuple[str, str], str] = {}
        for collection in report.get("collections") or []:
            name = str(collection.get("name") or "")
            for field in collection.get("fields") or []:
                output[(name, str(field.get("path") or ""))] = str(
                    field.get("dtype") or "unknown"
                )
        return output

    before = fields(checked)
    after = fields(live)
    added = [
        {"collection": key[0], "path": key[1], "dtype": after[key]}
        for key in sorted(after.keys() - before.keys())
    ]
    removed = [
        {"collection": key[0], "path": key[1], "dtype": before[key]}
        for key in sorted(before.keys() - after.keys())
    ]
    changed = [
        {
            "collection": key[0],
            "path": key[1],
            "before": before[key],
            "after": after[key],
        }
        for key in sorted(before.keys() & after.keys())
        if before[key] != after[key]
    ]
    return {
        "added": added,
        "removed": removed,
        "type_changed": changed,
        "has_drift": bool(added or removed or changed),
    }


def run_drift(
    tools: Path,
    checked_schema: Path,
    *,
    connection: str,
    out: Path,
    env_file: Path | None,
    experimental: bool,
) -> int:
    if not experimental:
        print("drift is experimental; pass --experimental", file=sys.stderr)
        return 2
    checked = _load_checked(checked_schema)
    live = asyncio.run(
        _introspect(
            tools,
            connection=connection,
            collections=None,
            env=_load_env(env_file),
        )
    )
    result = compare_schema(checked, live)
    result.update(
        {
            "experimental": True,
            "checked_schema": str(checked_schema),
            "connection": connection,
            "recommendation": (
                "review suggested schema changes and rerun eval; never auto-promote"
                if result["has_drift"]
                else "no schema drift detected"
            ),
        }
    )
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(f"wrote {out}", file=sys.stderr)
    return 1 if result["has_drift"] else 0
