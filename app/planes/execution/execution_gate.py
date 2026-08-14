"""
E. EXECUTION PLANE — Execution Gate (spec section 16)

    "This is the most important security boundary. The LLM must NOT
    directly call Java APIs. The LLM can only produce:
        {"tool_id": "...", "arguments": {...}}
    The Execution Gate must independently verify [10 checks] before
    calling the Java API."

Everything upstream of this module (Intent Engine, Planner, Context
Engine) is the LLM proposing what it THINKS should happen. Nothing it
produces is trusted until this gate re-derives and re-checks every
precondition from first principles — it does not trust upstream stages'
"looks fine" self-assessment, it re-verifies against the Tool Registry,
the actual resolved-parameter provenance ledger, the Policy Engine, and
the Approval Service directly. This is the ONLY function in the whole
codebase allowed to call api_fabric.execute() for a write/delete, and the
only one allowed to call it at all for anything risk-tiered above READ.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session as DBSession

from app.planes.control.context_engine import ResolvedParam
from app.planes.governance import approval_service, policy_engine
from app.planes.governance.missing_parameter_gate import check as missing_param_check
from app.planes.governance.risk_engine import RiskTier, requires_approval
from app.planes.governance.validation import validate
from app.planes.knowledge.tool_registry import ToolRegistry, ToolRegistryEntry, ToolStatus


@dataclass
class GateCheck:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class GateDecision:
    allowed: bool
    checks: list[GateCheck] = field(default_factory=list)
    tool: Optional[ToolRegistryEntry] = None
    executable_arguments: dict[str, Any] = field(default_factory=dict)

    @property
    def failure_reason(self) -> Optional[str]:
        for c in self.checks:
            if not c.passed:
                return f"{c.name}: {c.detail}"
        return None


# Simple in-process per-conversation rate limit — spec item 10 ("request
# is within limits"). Backed by cost_control.py for the token/call-budget
# version; this is the blunt per-turn ceiling that stops a single runaway
# planning loop from firing dozens of calls for one user message.
MAX_TOOL_CALLS_PER_TURN = 5


def evaluate(
    *,
    tool_id: str,
    proposed_arguments: dict[str, Any],
    resolved: dict[str, ResolvedParam],
    registry: ToolRegistry,
    authenticated: bool,
    role: Optional[str],
    tenant_id: Optional[str],
    session_tenant_id: Optional[str],
    approval_id: Optional[str],
    calls_this_turn: int,
    db: DBSession,
    session_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> GateDecision:
    checks: list[GateCheck] = []

    # 1. tool exists
    tool = registry.get_raw(tool_id)
    checks.append(GateCheck("tool_exists", tool is not None, "" if tool else f"'{tool_id}' not in registry"))
    if not tool:
        return GateDecision(False, checks)

    # 2. tool is enabled (ACTIVE)
    enabled = tool.status == ToolStatus.ACTIVE
    checks.append(GateCheck("tool_enabled", enabled, "" if enabled else f"status={tool.status.value}"))

    # 3. version is valid (non-empty content hash was computed at registry build time)
    version_valid = bool(tool.version)
    checks.append(GateCheck("version_valid", version_valid))

    # 4 + 5. arguments conform to schema / all required arguments exist —
    # re-run the Missing Parameter Gate here too (belt and suspenders: the
    # orchestrator should already have stopped upstream, but the gate
    # doesn't trust that it did).
    gate_result = missing_param_check(tool, resolved)
    checks.append(GateCheck("required_arguments_present", gate_result.passed,
                             "" if gate_result.passed else f"missing: {gate_result.missing}"))

    # 6. provenance is trusted — no LLM_GUESS or downgraded value may pass through
    executable = {k: v.value for k, v in resolved.items() if v.trusted}
    untrusted_but_proposed = set(proposed_arguments.keys()) - set(executable.keys())
    provenance_ok = True  # untrusted args are simply excluded, not a hard failure by themselves —
    # the missing-argument check above is what catches it if that exclusion
    # made a required field absent.
    checks.append(GateCheck("provenance_trusted", provenance_ok,
                             f"excluded untrusted: {sorted(untrusted_but_proposed)}" if untrusted_but_proposed else ""))

    # schema/type validation on whatever IS trusted and present
    param_meta = (
        tool.required_parameters
        + tool.optional_parameters
        + (tool.header_parameters or [])
        + (tool.file_parameters or [])
        + (tool.request_schema or [])
    )
    validation = validate(executable, param_meta)
    checks.append(GateCheck("schema_validation", validation.valid,
                             "" if validation.valid else "; ".join(f"{i.param}: {i.message}" for i in validation.issues)))

    # 7. user is authorized + 8. policy allows operation
    decision = policy_engine.evaluate(
        tool if enabled else None,
        authenticated=authenticated, role=role,
        tenant_id=tenant_id, session_tenant_id=session_tenant_id,
    )
    checks.append(GateCheck("authorized", decision.allowed, decision.reason if not decision.allowed else ""))

    # 9. approval exists if required — AND is bound to this EXACT action
    # (hash of tool_id + arguments), not just any approval for this tool.
    risk = tool.risk_level
    needs_approval = requires_approval(risk)
    approval_ok = True
    approval_detail = ""
    if needs_approval:
        if not approval_id:
            approval_ok = False
            approval_detail = f"risk tier {risk.value} requires approval, none was provided"
        else:
            approval_ok, approval_detail = approval_service.is_approved_for_action(
                db, approval_id, tool_id, executable, session_id=session_id, conversation_id=conversation_id
            )
            if approval_ok:
                approval_detail = ""
    checks.append(GateCheck("approval_present_if_required", approval_ok, approval_detail))

    # 10. request is within limits
    within_limits = calls_this_turn < MAX_TOOL_CALLS_PER_TURN
    checks.append(GateCheck("within_limits", within_limits,
                             "" if within_limits else f"exceeded {MAX_TOOL_CALLS_PER_TURN} tool calls this turn"))


    allowed = all(c.passed for c in checks)
    return GateDecision(allowed=allowed, checks=checks, tool=tool, executable_arguments=executable if allowed else {})
