"""
D. GOVERNANCE/SAFETY PLANE — Missing Parameter Gate (spec section 9)

Pure, deterministic set arithmetic — required_parameters minus
trusted_available_parameters. No LLM call happens here; by the time
execution reaches this gate, context_engine.py has already decided what's
trusted. This module just enforces the stop-and-ask rule and writes a
single, consolidated clarification question rather than one question per
missing field.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.agent.param_utils import is_body_field_required
from app.planes.control.context_engine import ResolvedParam
from app.planes.knowledge.tool_registry import ToolRegistryEntry

# Human-friendly phrasing for common raw param names — falls back to the
# raw name (space-cased) for anything not listed, so this never blocks on
# an unlisted field, it just asks with a slightly less polished label.
_FRIENDLY_NAMES = {
    "employeeId": "the employee", "leaveType": "the leave type", "type": "the leave type",
    "startDate": "the start date", "endDate": "the end date", "reason": "a reason",
    "id": "which record (its ID)", "amount": "the amount", "categoryId": "the category",
}


@dataclass
class GateResult:
    passed: bool
    missing: list[str]
    clarification_question: str | None


def _friendly(name: str) -> str:
    if name in _FRIENDLY_NAMES:
        return _FRIENDLY_NAMES[name]
    import re
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", name).lower()
    return spaced


def _schema_fields(tool: ToolRegistryEntry) -> list[dict]:
    if tool.request_schema:
        return list(tool.request_schema)
    for mp in tool.multipart_parts or []:
        if mp.get("part_type") == "json_dto" and mp.get("schema"):
            return list(mp["schema"])
    return []


def check(tool: ToolRegistryEntry, resolved: dict[str, ResolvedParam]) -> GateResult:
    # 1. PATH and QUERY required parameters
    required_names = {p["name"] for p in tool.required_parameters if p.get("name")}

    # 2. HEADER required parameters
    for hp in tool.header_parameters:
        if hp.get("required") and hp.get("name"):
            required_names.add(hp["name"])

    # 3. MULTIPART required parts (file/scalar only — dto fields handled below)
    for mp in tool.multipart_parts:
        if mp.get("required") and mp.get("name"):
            if mp.get("part_type") in ("file", "scalar"):
                required_names.add(mp["name"])

    # 4. REQUEST BODY / multipart DTO fields
    # Catalog historically has required=False/missing on every body field.
    # Use heuristics so writes don't execute with empty JSON.
    if tool.http_method in ("POST", "PUT", "PATCH"):
        for field in _schema_fields(tool):
            if field.get("name") and is_body_field_required(field, http_method=tool.http_method):
                required_names.add(field["name"])

    trusted_names = {k for k, v in resolved.items() if v.trusted}
    # Session employee id satisfies employeeId without an explicit USER claim
    # when already injected as trusted SESSION upstream — handled by trusted_names.

    missing = sorted(required_names - trusted_names)

    if not missing:
        return GateResult(passed=True, missing=[], clarification_question=None)

    friendly = [_friendly(m) for m in missing]
    if len(friendly) == 1:
        question = f"I need {friendly[0]} before I can do this — could you provide it?"
    else:
        question = "I need a few more details before I can do this: " + ", ".join(friendly) + "."
    return GateResult(passed=False, missing=missing, clarification_question=question)
