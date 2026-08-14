"""
B.3.7 PARAMETER / CONTEXT ENGINE (spec section 8-9)

The single most important correctness property in the whole pipeline:
every parameter value that reaches execution must carry PROVENANCE (where
it came from) and a TRUSTED flag, and only trusted, non-guess values are
ever executable. An LLM still does the extraction (there's no other way
to turn "next Monday" into an ISO date from free text) — but the LLM is
required to self-report a source for each value, and this module
independently CROSS-CHECKS every claimed source against the actual
trusted context it claims to come from. A claim that doesn't check out is
downgraded to untrusted, exactly like an outright LLM_GUESS — the
downstream Missing Parameter Gate then treats it as absent and asks the
user, rather than silently trusting the LLM's self-report.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ParamSource(str, Enum):
    USER = "USER"                # explicitly present in the current user message
    SESSION = "SESSION"          # the authenticated session (employee_id, tenant, role)
    IDENTITY = "IDENTITY"        # same bucket as SESSION, kept distinct for claims that
                                  # specifically come from decoded identity claims vs. app session state
    API_RESULT = "API_RESULT"    # output of a previous, validated tool call this turn/conversation
    MEMORY = "MEMORY"            # approved long-term memory (see knowledge/memory.py)
    SYSTEM = "SYSTEM"            # deterministically computed by the system itself (timestamps, request ids)
    LLM_GUESS = "LLM_GUESS"      # explicitly never trusted, never executable


UNTRUSTED_SOURCES = {ParamSource.LLM_GUESS}


@dataclass
class ResolvedParam:
    value: Any
    source: ParamSource
    trusted: bool
    note: Optional[str] = None  # why it was downgraded, if it was
    raw_value: Optional[str] = None
    normalized_value: Optional[Any] = None

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "source": self.source.value,
            "trusted": self.trusted,
            "note": self.note,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
        }


class LLMExtractedParam(BaseModel):
    """What the planner LLM is required to output for EACH parameter it
    fills — value plus a self-reported source. This is the only channel
    through which the LLM can propose a parameter value; it can never
    write straight into an executable argument dict."""
    name: str
    value: Any
    claimed_source: ParamSource
    quote_or_basis: str = Field(description="The exact phrase from the user message, session, prior result, "
                                             "or memory that grounds this value — empty string only if claimed_source is LLM_GUESS")
    raw_value: Optional[str] = None


class TrustedContext(BaseModel):
    """Everything a claimed source can be checked against."""
    model_config = {"arbitrary_types_allowed": True}
    user_message: str
    employee_id: Optional[str] = None
    role: Optional[str] = None
    tenant_id: Optional[str] = None
    prior_api_results: dict[str, Any] = Field(default_factory=dict)  # tool_id -> last result body, this conversation
    memory_facts: dict[str, Any] = Field(default_factory=dict)       # approved long-term memory, see knowledge/memory.py


def _cross_check(param: LLMExtractedParam, ctx: TrustedContext) -> ResolvedParam:
    src = param.claimed_source
    raw = param.raw_value or param.quote_or_basis or str(param.value)
    norm = param.value

    if src == ParamSource.LLM_GUESS:
        return ResolvedParam(param.value, src, trusted=False, note="explicitly self-reported as a guess", raw_value=raw, normalized_value=norm)

    if src == ParamSource.USER:
        basis = (param.quote_or_basis or "").strip()
        if not basis or basis.lower() not in ctx.user_message.lower():
            return ResolvedParam(param.value, ParamSource.LLM_GUESS, trusted=False,
                                  note="claimed USER source but basis text not found in the actual user message", raw_value=raw, normalized_value=norm)
        return ResolvedParam(param.value, src, trusted=True, raw_value=raw, normalized_value=norm)

    if src in (ParamSource.SESSION, ParamSource.IDENTITY):
        session_values = {str(v) for v in (ctx.employee_id, ctx.role, ctx.tenant_id) if v is not None}
        if str(param.value) not in session_values:
            return ResolvedParam(param.value, ParamSource.LLM_GUESS, trusted=False,
                                  note=f"claimed {src.value} source but value doesn't match the actual session", raw_value=raw, normalized_value=norm)
        return ResolvedParam(param.value, src, trusted=True, raw_value=raw, normalized_value=norm)

    if src == ParamSource.API_RESULT:
        flat_values = _flatten_values(ctx.prior_api_results)
        if str(param.value) not in flat_values:
            return ResolvedParam(param.value, ParamSource.LLM_GUESS, trusted=False,
                                  note="claimed API_RESULT source but value not found in any prior validated result", raw_value=raw, normalized_value=norm)
        return ResolvedParam(param.value, src, trusted=True, raw_value=raw, normalized_value=norm)

    if src == ParamSource.MEMORY:
        flat_values = _flatten_values(ctx.memory_facts)
        if str(param.value) not in flat_values:
            return ResolvedParam(param.value, ParamSource.LLM_GUESS, trusted=False,
                                  note="claimed MEMORY source but value not found in approved memory facts", raw_value=raw, normalized_value=norm)
        return ResolvedParam(param.value, src, trusted=True, raw_value=raw, normalized_value=norm)

    if src == ParamSource.SYSTEM:
        return ResolvedParam(param.value, ParamSource.LLM_GUESS, trusted=False,
                              note="SYSTEM source can only be injected by the platform, not claimed by the LLM", raw_value=raw, normalized_value=norm)

    return ResolvedParam(param.value, ParamSource.LLM_GUESS, trusted=False, note="unrecognized source", raw_value=raw, normalized_value=norm)


def _flatten_values(obj: Any, depth: int = 0) -> set[str]:
    if depth > 6:
        return set()
    out: set[str] = set()
    if isinstance(obj, dict):
        for v in obj.values():
            out |= _flatten_values(v, depth + 1)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out |= _flatten_values(v, depth + 1)
    elif obj is not None:
        out.add(str(obj))
    return out


def resolve_parameters(extracted: list[LLMExtractedParam], ctx: TrustedContext) -> dict[str, ResolvedParam]:
    return {p.name: _cross_check(p, ctx) for p in extracted}


def inject_system_params(resolved: dict[str, ResolvedParam], param_names: set[str]) -> dict[str, ResolvedParam]:
    """The ONLY legitimate way a param gets ParamSource.SYSTEM — computed
    here, never claimed by the LLM. Currently: request timestamps / dates
    the tool's own schema names in a recognizable way. Extend as needed."""
    out = dict(resolved)
    now_iso = datetime.now().isoformat()
    today_iso = date.today().isoformat()
    system_values = {"currentTimestamp": now_iso, "requestTimestamp": now_iso, "today": today_iso}
    for name in param_names:
        if name in system_values and name not in out:
            out[name] = ResolvedParam(system_values[name], ParamSource.SYSTEM, trusted=True)
    return out


def executable_values(resolved: dict[str, ResolvedParam]) -> dict[str, Any]:
    """Only values that survived cross-checking as trusted — this is what
    is allowed to flow into the Execution Gate. Untrusted/guessed values
    are dropped here, which is exactly what makes them "missing" for the
    Missing Parameter Gate downstream."""
    return {k: v.value for k, v in resolved.items() if v.trusted}


def missing_after_resolution(required_names: set[str], resolved: dict[str, ResolvedParam]) -> list[str]:
    trusted_names = {k for k, v in resolved.items() if v.trusted}
    return sorted(required_names - trusted_names)
