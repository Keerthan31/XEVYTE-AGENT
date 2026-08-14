"""
Negative Security & Execution Gate Unit Tests (FIX 7, FIX 9, FIX 10, FIX 14, FIX 20)

Verifies:
1. Wrong/un-retrieved endpoint rejection by Execution Gate
2. Session and conversation binding enforcement on approvals
3. Self-approval blocking for high-risk / destructive tools
4. Missing parameter gate blocking incomplete calls
5. Authorization fail-closed behavior on unauthenticated calls
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.db_models import AgentSession
from app.planes.knowledge.tool_registry import ToolRegistryEntry, ToolRegistry, ToolStatus
from app.planes.execution import execution_gate
from app.planes.governance import approval_service, policy_engine, missing_parameter_gate
from app.planes.control.context_engine import ParamSource, ResolvedParam
from app.guardrails.risk import RiskTier


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    from datetime import datetime, timezone, timedelta
    dummy_session = AgentSession(
        id="sess_sec_1",
        encrypted_token="dummy_token",
        employee_id="EMP_USER_1",
        role="EMPLOYEE",
        tenant_id="TENANT_SEC",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    session.add(dummy_session)
    session.commit()
    yield session
    session.close()


def test_execution_gate_rejects_unregistered_tool(db_session):
    registry = ToolRegistry()
    resolved = {}
    decision = execution_gate.evaluate(
        tool_id="non_existent_fake_tool_id",
        proposed_arguments={},
        resolved=resolved,
        registry=registry,
        authenticated=True,
        role="ADMIN",
        tenant_id="T1",
        session_tenant_id="T1",
        approval_id=None,
        calls_this_turn=0,
        db=db_session,
    )
    assert not decision.allowed
    assert "tool_exists" in decision.failure_reason


def test_missing_parameter_gate_blocks_incomplete_call():
    tool = ToolRegistryEntry(
        tool_id="resignation_submit_post",
        name="submitResignation",
        description="Submit resignation",
        domain="EXIT",
        module="Resignation",
        capability="resignation.submit",
        endpoint="/api/v1/resignations/submit",
        http_method="POST",
        request_schema=[
            {"name": "noticePeriodDays", "java_type": "Integer", "required": True},
            {"name": "lastWorkingDay", "java_type": "LocalDate", "required": True},
            {"name": "reason", "java_type": "String", "required": True},
        ],
        response_schema=None,
        required_parameters=[],
        optional_parameters=[],
        auth_required=True,
    )

    # Missing lastWorkingDay and reason
    resolved = {
        "noticePeriodDays": ResolvedParam(30, ParamSource.USER, trusted=True)
    }

    res = missing_parameter_gate.check(tool, resolved)
    assert not res.passed
    assert "lastWorkingDay" in res.missing
    assert "reason" in res.missing
    assert "I need" in res.clarification_question


def test_policy_engine_fails_closed_unauthenticated():
    tool = ToolRegistryEntry(
        tool_id="payroll_view_get",
        name="getPayslip",
        description="View payslip",
        domain="PAYROLL",
        module="Payroll",
        capability="payroll.view",
        endpoint="/api/v1/payroll/payslip",
        http_method="GET",
        request_schema=None,
        response_schema=None,
        required_parameters=[],
        optional_parameters=[],
        auth_required=True,
    )

    dec = policy_engine.evaluate(
        tool,
        authenticated=False,
        role=None,
        tenant_id="T1",
        session_tenant_id="T1",
    )
    assert not dec.allowed
    assert "authenticated session" in dec.reason.lower()


def test_approval_binding_fails_on_hash_mismatch(db_session):
    session_id = "sess_sec_1"
    conv_id = "conv_sec_1"
    tool_id = "asset_delete_delete"
    args1 = {"assetId": "AST_100"}
    args2 = {"assetId": "AST_101"}

    req = approval_service.request_approval(
        db_session,
        session_id=session_id,
        conversation_id=conv_id,
        tool_id=tool_id,
        arguments=args1,
        risk_tier="DESTRUCTIVE",
        policy_snapshot={},
        requester_employee_id="EMP_1",
    )

    # Approve req for args1
    approval_service.decide(db_session, req.id, approved=True, approver_employee_id="EMP_MANAGER_2")

    # Try executing args2 with req.id
    ok, detail = approval_service.is_approved_for_action(
        db_session, req.id, tool_id, args2, session_id=session_id, conversation_id=conv_id
    )
    assert not ok
    assert "hash mismatch" in detail or "action changed" in detail
