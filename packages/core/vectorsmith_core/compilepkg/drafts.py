"""Draft creation and promotion. Drafts never mutate a serving Project."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from vectorsmith_core.compilepkg.validator import validate
from vectorsmith_core.tds.models import StaticFilter, StaticFilters, ToolSpec

if TYPE_CHECKING:
    from vectorsmith_core.api import Project, ToolDraft

READ_ONLY = frozenset({"search", "lookup", "count", "scroll", "pipeline"})


def _issues_from_pydantic(exc: ValidationError) -> list[Any]:
    from vectorsmith_core.api import Issue

    out: list[Any] = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", ()))
        out.append(
            Issue(
                severity="error",
                code="VB2001",
                message=err.get("msg", "invalid tool spec"),
                path=loc or None,
            )
        )
    return out


def draft_tool(project: Project, provenance: dict[str, Any], proposed: dict[str, Any]) -> ToolDraft:
    """Validate ``proposed`` as a ToolSpec. Never mutates ``project``."""
    from vectorsmith_core.api import Issue, ToolDraft

    try:
        spec = ToolSpec.model_validate(proposed)
    except ValidationError as exc:
        dummy = ToolSpec.model_validate(
            {
                "name": "draft_invalid_tool",
                "description": "Invalid pending draft retained for issue reporting.",
                "kind": "search",
                "target": {"connection": "invalid", "collection": "invalid"},
            }
        )
        return ToolDraft(
            spec=dummy,
            validator_issues=_issues_from_pydantic(exc),
            provenance=_provenance(provenance, proposed),
            status="pending",
        )

    issues: list[Any] = []
    if spec.kind not in READ_ONLY:
        issues.append(
            Issue(
                severity="error",
                code="VB2017",
                message="drafts may only use read-only kinds",
                tool=spec.name,
            )
        )

    # Auto-attach connection static filters — drafts cannot remove them.
    tds = getattr(project, "tds", None)
    if tds is not None and spec.target and spec.target.connection in tds.connections:
        conn = tds.connections[spec.target.connection]
        attached = list(conn.builtin_defaults.static_filters.must)
        if attached:
            have = {(s.path, s.op, s.value) for s in spec.static_filters.must}
            merged = list(spec.static_filters.must)
            for sf in attached:
                key = (sf.path, sf.op, sf.value)
                if key not in have:
                    merged.append(StaticFilter(path=sf.path, op=sf.op, value=sf.value))
            spec = spec.model_copy(
                update={
                    "static_filters": StaticFilters(
                        must=merged, must_not=list(spec.static_filters.must_not)
                    )
                }
            )

    if tds is not None:
        trial = tds.model_copy(update={"tools": list(tds.tools) + [spec]})
        issues.extend(validate(trial))

    return ToolDraft(
        spec=spec,
        validator_issues=issues,
        provenance=_provenance(provenance, proposed),
        status="pending",
    )


def promote_draft(draft: ToolDraft, project: Project) -> ToolSpec:
    """Re-validate and return the ToolSpec to insert. Refuses on error issues."""
    from vectorsmith_core.api import Issue
    from vectorsmith_core.errors import TDSValidationError

    tds = project.tds
    trial = tds.model_copy(update={"tools": list(tds.tools) + [draft.spec]})
    issues = validate(trial)
    errors = [i for i in issues if getattr(i, "severity", None) == "error"]
    if errors:
        raise TDSValidationError(errors, detail="draft has error-severity issues")
    # keep validator_issues in sync
    draft.validator_issues = [i if isinstance(i, Issue) else i for i in issues]
    return draft.spec


def _provenance(base: dict[str, Any], proposed: dict[str, Any]) -> dict[str, Any]:
    blob = json.dumps(proposed, sort_keys=True, default=str).encode()
    out = dict(base)
    out.setdefault("created_by", "define_tool")
    out["hash"] = hashlib.sha256(blob).hexdigest()
    return out
