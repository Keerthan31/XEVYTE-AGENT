"""
D. GOVERNANCE/SAFETY PLANE — Validation Engine (spec section 10)

Validates resolved, trusted parameter VALUES against the tool's actual
schema (java_type from the auto-discovered catalog) before they're
allowed anywhere near the Execution Gate. This catches "trusted but
wrong-shaped" data — e.g. a USER-sourced date string that isn't ISO
format — which provenance checking alone (context_engine.py) doesn't
cover, since a value can be legitimately grounded in the user's message
and still be malformed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_NUMERIC_TYPES = {"int", "integer", "long", "double", "float", "biginteger", "bigdecimal", "short"}
_BOOL_TYPES = {"boolean", "bool"}
_STRING_LIST_TYPES = ("list<string>", "list<java.lang.string>")


@dataclass
class ValidationIssue:
    param: str
    message: str


@dataclass
class ValidationResult:
    valid: bool
    issues: list[ValidationIssue]


def _type_hint_from_name(name: str, params_meta: list[dict]) -> str | None:
    for p in params_meta:
        if p["name"] == name:
            return p.get("java_type", "").lower()
    return None


def _validate_one(name: str, value: Any, java_type_hint: str | None) -> ValidationIssue | None:
    if value is None or value == "":
        return ValidationIssue(name, "value is empty")

    hint = (java_type_hint or "").lower()

    if hint in _NUMERIC_TYPES:
        try:
            float(value)
        except (TypeError, ValueError):
            return ValidationIssue(name, f"expected a number, got {value!r}")

    elif hint in _BOOL_TYPES:
        if str(value).lower() not in ("true", "false"):
            return ValidationIssue(name, f"expected true/false, got {value!r}")

    elif "date" in hint and "time" not in hint:
        if not _DATE_RE.match(str(value)):
            return ValidationIssue(name, f"expected an ISO date (YYYY-MM-DD), got {value!r}")

    elif "localdatetime" in hint or "instant" in hint or ("date" in hint and "time" in hint):
        if not (_DATE_RE.match(str(value)) or _DATETIME_RE.match(str(value))):
            return ValidationIssue(name, f"expected an ISO date/datetime, got {value!r}")

    # heuristic cross-field-adjacent check: *Id fields should not be empty/whitespace-only
    if name.lower().endswith("id") and isinstance(value, str) and not value.strip():
        return ValidationIssue(name, "id value is blank")

    return None


def validate(values: dict[str, Any], param_metadata: list[dict]) -> ValidationResult:
    """param_metadata is the tool's required_parameters + optional_parameters
    + (for body fields) request_schema — anything with a 'name'/'java_type'
    shape works. Only params actually present in `values` are checked;
    missing-ness is the Missing Parameter Gate's job, not this one's."""
    issues: list[ValidationIssue] = []
    for name, value in values.items():
        hint = _type_hint_from_name(name, param_metadata)
        issue = _validate_one(name, value, hint)
        if issue:
            issues.append(issue)
    return ValidationResult(valid=not issues, issues=issues)


def validate_date_range(start: str | None, end: str | None) -> ValidationIssue | None:
    """Common cross-field business constraint reused by several
    write-path tools (leave, travel, claims) — end must not precede start."""
    if not start or not end:
        return None
    try:
        s = datetime.fromisoformat(start[:10])
        e = datetime.fromisoformat(end[:10])
    except ValueError:
        return None  # format issue already caught by the per-field check above
    if e < s:
        return ValidationIssue("endDate", f"end date {end} is before start date {start}")
    return None
