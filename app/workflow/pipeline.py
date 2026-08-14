"""
Master orchestration — the actual 18-step pipeline, wiring every plane
module built in app/planes/* into one working flow. This replaces the
original app/agent/graph.py (kept in place, untouched, for reference/
rollback) with the enterprise-spec pipeline:

Intent -> Domain -> Tool Discovery -> Planner -> Context/Provenance ->
Missing Param Gate -> Validation -> Policy -> Risk -> Approval ->
Execution Gate -> API Fabric -> Result Validator -> Error Recovery ->
Response Generator

Durable state: each call is tracked in workflow_runs (db_models.py) with
the named states from the spec (RECEIVED..COMPLETED/FAILED/ESCALATED).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.orm import Session as DBSession

from app.db_models import WorkflowRun
from app.guardrails import safety
from app.planes.control import intent_engine, planner, response_generator
from app.planes.control.context_engine import TrustedContext, executable_values, resolve_parameters
from app.planes.control.domain_router import Domain
from app.planes.control.tool_discovery import discover
from app.planes.execution import api_fabric, error_recovery, execution_gate, result_validator
from app.planes.governance import approval_service
from app.planes.governance.missing_parameter_gate import check as missing_param_check
from app.planes.governance.risk_engine import requires_approval
from app.planes.knowledge.tool_registry import get_tool_registry


@dataclass
class PipelineResult:
    status: str  # needs_clarification | needs_info | needs_confirmation | completed | error | capability_not_available
    reply: str
    tool_id: Optional[str] = None
    risk_tier: Optional[str] = None
    pending_approval_id: Optional[str] = None
    normalized_result: Optional[dict] = None
    run_id: Optional[str] = None


def _set_state(db: DBSession, run: WorkflowRun, state: str, **fields) -> None:
    run.state = state
    for k, v in fields.items():
        setattr(run, k, v)
    db.commit()


async def handle_message(
    db: DBSession,
    *,
    conversation_id: str,
    session_id: str,
    employee_id: Optional[str],
    role: Optional[str],
    tenant_id: Optional[str],
    bearer_token: Optional[str],
    user_message: str,
    conversation_history: list[dict],
    prior_api_results: dict[str, Any] | None = None,
) -> PipelineResult:
    run = WorkflowRun(conversation_id=conversation_id, session_id=session_id, employee_id=employee_id,
                       user_message=user_message, state="RECEIVED")
    db.add(run)
    db.commit()
    db.refresh(run)

    # ---- input safety ----
    warnings = safety.scan_user_input(user_message)
    if "token_exfiltration_attempt" in warnings:
        _set_state(db, run, "FAILED", error_category="SAFETY")
        return PipelineResult("error", "I can't share session tokens or credentials.", run_id=run.id)

    # ---- 1. Intent Engine ----
    _set_state(db, run, "UNDERSTANDING")
    intent = intent_engine.classify(user_message, conversation_history)
    _set_state(db, run, "UNDERSTANDING", intent=intent.intent, domain=intent.domain)

    if intent_engine.needs_clarification(intent):
        _set_state(db, run, "WAITING_FOR_CLARIFICATION")
        return PipelineResult("needs_clarification", intent_engine.clarification_question(intent), run_id=run.id)

    # ---- 2/3. Domain Router + Tool Discovery (hybrid) ----
    try:
        domain = Domain(intent.domain.upper())
    except ValueError:
        domain = Domain.UNKNOWN
    candidates = discover(user_message, domain=domain, top_k=12)
    if not candidates:
        _set_state(db, run, "FAILED", error_category="NO_CAPABILITY")
        return PipelineResult("capability_not_available",
                               "I don't have an action available for that yet — could you rephrase, "
                               "or is this something outside what I can currently do?", run_id=run.id)

    # ---- 4/5/6. Tool Understanding (implicit in candidate contract) + Planner ----
    _set_state(db, run, "PLANNING")
    plan_result = planner.plan(user_message, intent, candidates, conversation_history, employee_id, role)

    registry = get_tool_registry()
    tool = registry.get(plan_result.tool_id) if plan_result.tool_id else None
    if not tool:
        _set_state(db, run, "FAILED", error_category="NO_TOOL_SELECTED")
        return PipelineResult("capability_not_available",
                               "I couldn't confidently match that to a specific action — could you be more specific?",
                               run_id=run.id)
    _set_state(db, run, "PLANNING", tool_id=tool.tool_id)

    # ---- 7. Context Engine — provenance resolution ----
    ctx = TrustedContext(
        user_message=user_message, employee_id=employee_id, role=role, tenant_id=tenant_id,
        prior_api_results=prior_api_results or {},
    )
    extracted = planner.to_extracted_params(plan_result)
    resolved = resolve_parameters(extracted, ctx)

    # ---- 8. Missing Parameter Gate ----
    gate = missing_param_check(tool, resolved)
    if not gate.passed:
        _set_state(db, run, "WAITING_FOR_CLARIFICATION")
        return PipelineResult("needs_info", gate.clarification_question, tool_id=tool.tool_id, run_id=run.id)

    executable = executable_values(resolved)

    # ---- 9-11. Validation / Policy / Risk are re-verified independently
    # inside the Execution Gate itself (13) — see execution_gate.py, which
    # is deliberately the single place that re-derives all of them rather
    # than trusting a "passed" flag computed upstream.

    # ---- 12. Approval, if this risk tier needs it ----
    risk = tool.risk_level
    if requires_approval(risk):
        existing_approval_id = None  # a fresh turn never has one yet — the confirm route provides it
        if not existing_approval_id:
            approval = approval_service.request_approval(
                db, session_id=session_id, conversation_id=conversation_id, tool_id=tool.tool_id,
                arguments=executable, risk_tier=risk.value, policy_snapshot={"role": role, "tenant_id": tenant_id},
                requester_employee_id=employee_id,
            )
            _set_state(db, run, "WAITING_FOR_APPROVAL", tool_id=tool.tool_id)
            summary = (f"This will call **{tool.http_method} {tool.endpoint}** ({tool.module}) — "
                       f"risk tier {risk.value}.")
            if executable:
                from app.guardrails.pii import redact
                summary += f"\n\nWith: {redact(executable)}"
            summary += "\n\nShould I go ahead?"
            return PipelineResult("needs_confirmation", summary, tool_id=tool.tool_id, risk_tier=risk.value,
                                   pending_approval_id=approval.id, run_id=run.id)

    return await _execute_and_respond(db, run, tool, executable, resolved, employee_id, role, tenant_id,
                                       bearer_token, user_message, approval_id=None, calls_this_turn=0)


async def resume_after_approval(
    db: DBSession, *, run_id: str, approval_id: str, approved: bool, bearer_token: Optional[str],
    employee_id: Optional[str], role: Optional[str], tenant_id: Optional[str], user_message: str,
) -> PipelineResult:
    run = db.get(WorkflowRun, run_id)
    if not run:
        return PipelineResult("error", "That request no longer exists.")

    if not approved:
        _set_state(db, run, "FAILED", error_category="USER_DECLINED")
        return PipelineResult("completed", "Okay, I won't go ahead with that.", run_id=run.id)

    registry = get_tool_registry()
    tool = registry.get(run.tool_id)
    if not tool:
        _set_state(db, run, "FAILED", error_category="TOOL_MISSING")
        return PipelineResult("error", "That action is no longer available.", run_id=run.id)

    # FIX 9: Decrypt and use protected execution arguments, NEVER display arguments_summary
    executable = approval_service.get_executable_arguments(db, approval_id)
    from app.planes.control.context_engine import ParamSource, ResolvedParam
    resolved = {k: ResolvedParam(v, ParamSource.USER, trusted=True) for k, v in executable.items()}

    return await _execute_and_respond(db, run, tool, executable, resolved, employee_id, role, tenant_id,
                                       bearer_token, user_message, approval_id=approval_id, calls_this_turn=0)


async def _execute_and_respond(
    db: DBSession, run: WorkflowRun, tool, executable: dict, resolved: dict,
    employee_id, role, tenant_id, bearer_token, user_message, *, approval_id: Optional[str], calls_this_turn: int,
) -> PipelineResult:
    # ---- 13. EXECUTION GATE — re-verifies everything independently ----
    _set_state(db, run, "EXECUTING", tool_id=tool.tool_id)
    decision = execution_gate.evaluate(
        tool_id=tool.tool_id, proposed_arguments=executable, resolved=resolved, registry=get_tool_registry(),
        authenticated=bool(bearer_token), role=role, tenant_id=tenant_id, session_tenant_id=tenant_id,
        approval_id=approval_id, calls_this_turn=calls_this_turn, db=db,
        session_id=run.session_id, conversation_id=run.conversation_id,
    )
    if not decision.allowed:
        _set_state(db, run, "FAILED", error_category="GATE_DENIED")
        reply = await response_generator.generate(user_message, refusal_reason=decision.failure_reason)
        return PipelineResult("error", reply, tool_id=tool.tool_id, run_id=run.id)

    # ---- 14. API Fabric (circuit breaker, idempotency, retry) ----
    raw = await api_fabric.execute_with_fabric(tool, decision.executable_arguments, bearer_token=bearer_token)

    # ---- 16. Result Validator ----
    normalized = result_validator.normalize(tool.tool_id, raw)

    # ---- FIX 18. Audit Logging ----
    from app.db_models import AuditLog
    from app.guardrails.pii import redact
    audit_entry = AuditLog(
        session_id=run.session_id,
        conversation_id=run.conversation_id,
        employee_id=employee_id,
        endpoint_id=tool.tool_id,
        http_method=tool.http_method,
        path=tool.endpoint,
        risk_tier=tool.risk_level.value,
        user_confirmed=bool(approval_id),
        request_summary=redact(decision.executable_arguments),
        response_status=normalized.status_code,
        response_summary=redact(normalized.data or {"error": normalized.error}),
        success=normalized.success,
        error_message=normalized.error,
        latency_ms=raw.get("latency_ms", 0),
    )
    db.add(audit_entry)
    db.commit()

    if not normalized.success:
        # ---- 17. Error Recovery ----
        err_decision = error_recovery.decide(normalized.status_code, normalized.error)
        _set_state(db, run, "FAILED" if err_decision.strategy.value != "RETRY" else "RETRYING",
                   error_category=err_decision.category.value)
        reply = await response_generator.generate(user_message, error_decision=err_decision)
        return PipelineResult("error", reply, tool_id=tool.tool_id, risk_tier=tool.risk_level.value,
                               normalized_result=normalized.to_dict(), run_id=run.id)

    # ---- 18. Response Generator ----
    _set_state(db, run, "COMPLETED")
    reply = await response_generator.generate(user_message, normalized=normalized)
    return PipelineResult("completed", reply, tool_id=tool.tool_id, risk_tier=tool.risk_level.value,
                           normalized_result=normalized.to_dict(), run_id=run.id)

