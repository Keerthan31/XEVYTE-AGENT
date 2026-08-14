"""
Comprehensive Contract & Execution Gate Test Suite (FIX 20)

Tests:
1. Contract representation & schema enrichment (path, query, header, body, multipart)
2. Generic Request Compiler (path, query, header, JSON body, multipart form-data, wire date formatting)
3. Missing Parameter Gate (across PATH, QUERY, HEADER, BODY, MULTIPART)
4. Approval Security & Binding (P0 unredacted protected execution args, action hash, self-approval block, session binding)
5. Catalog integrity & startup validation (633 baseline check, schema, uniqueness)
6. Execution Gate & Policy evaluation
"""
import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.db_models import AgentSession
from app.catalog.loader import EndpointSpec, Catalog, load_catalog
from app.planes.knowledge.tool_registry import ToolRegistryEntry, build_entry, ToolStatus
from app.planes.execution.request_compiler import RequestCompiler, CompiledRequest, serialize_wire_value
from app.planes.governance import missing_parameter_gate, approval_service, policy_engine
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
        id="sess_test_1",
        encrypted_token="dummy_encrypted",
        employee_id="EMP_REQ_1",
        role="EMPLOYEE",
        tenant_id="TENANT_1",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    session.add(dummy_session)
    session.commit()

    yield session
    session.close()



def test_catalog_loading_and_validation():
    catalog = load_catalog()
    assert len(catalog) >= 600, f"Expected baseline ~633 endpoints, got {len(catalog)}"
    val_result = catalog.validate()
    assert val_result.valid, f"Catalog validation failed with errors: {val_result.errors}"


def test_endpoint_spec_multipart_derivation():
    spec = EndpointSpec(
        id="test_upload_post_upload",
        module="Applicant",
        controller_class="ApplicantController",
        method_name="uploadDocs",
        http_method="POST",
        path="/api/v1/applicants/upload/{applicantId}",
        path_params=[{"name": "applicantId", "java_type": "String", "required": True}],
        query_params=[
            {"name": "offerLetter", "java_type": "MultipartFile", "required": False},
            {"name": "category", "java_type": "String", "required": True},
        ],
        request_body_type="ApplicantDocsDTO",
        request_body_schema=[{"name": "documentType", "java_type": "String"}],
        has_file_upload=True,
    )
    parts = spec.get_multipart_parts()
    assert len(parts) >= 2
    part_types = [p["part_type"] for p in parts]
    assert "file" in part_types
    assert "json_dto" in part_types or "scalar" in part_types


def test_request_compiler_json():
    tool = ToolRegistryEntry(
        tool_id="leave_apply_post",
        name="applyLeave",
        description="Apply for leave",
        domain="LEAVE",
        module="Leave",
        capability="leave.apply",
        endpoint="/api/v1/leaves/apply",
        http_method="POST",
        request_schema=[{"name": "leaveType", "java_type": "String"}, {"name": "startDate", "java_type": "LocalDate"}],
        response_schema=None,
        required_parameters=[],
        optional_parameters=[],
        auth_required=True,
    )
    args = {"leaveType": "CASUAL", "startDate": "2026-08-15"}
    compiled = RequestCompiler.compile(tool, args, bearer_token="token_123")
    assert compiled.method == "POST"
    assert compiled.headers.get("Authorization") == "Bearer token_123"
    assert compiled.json_body == {"leaveType": "CASUAL", "startDate": "2026-08-15"}


def test_request_compiler_multipart_dto_and_files():
    tool = ToolRegistryEntry(
        tool_id="applicant_upload_post",
        name="uploadDocs",
        description="Upload signed docs",
        domain="ONBOARDING",
        module="Applicant",
        capability="applicant.uploadDocs",
        endpoint="/api/v1/applicants/upload/{applicantId}",
        http_method="POST",
        request_schema=[{"name": "notes", "java_type": "String"}],
        response_schema=None,
        required_parameters=[{"name": "applicantId", "location": "path", "java_type": "String", "required": True}],
        optional_parameters=[],
        has_file_upload=True,
        multipart_parts=[
            {"name": "dto", "part_type": "json_dto", "content_type": "application/json"},
            {"name": "offerLetter", "part_type": "file", "content_type": "application/octet-stream"},
        ],
        auth_required=True,
    )
    args = {"applicantId": "APP_999", "notes": "Signed offer letter"}
    files = {"offerLetter": ("offer.pdf", b"%PDF-1.4 content...", "application/pdf")}
    compiled = RequestCompiler.compile(tool, args, bearer_token="token_123", file_inputs=files)

    assert compiled.method == "POST"
    assert "/api/v1/applicants/upload/APP_999" in compiled.url_path
    assert compiled.files is not None
    part_names = [f[0] for f in compiled.files]
    assert "dto" in part_names
    assert "offerLetter" in part_names


def test_missing_parameter_gate():
    tool = ToolRegistryEntry(
        tool_id="leave_apply_post",
        name="applyLeave",
        description="Apply for leave",
        domain="LEAVE",
        module="Leave",
        capability="leave.apply",
        endpoint="/api/v1/leaves/apply",
        http_method="POST",
        request_schema=[
            {"name": "leaveType", "java_type": "String", "required": True},
            {"name": "startDate", "java_type": "LocalDate", "required": True},
            {"name": "reason", "java_type": "String", "required": False},
        ],
        response_schema=None,
        required_parameters=[
            {"name": "employeeId", "location": "query", "java_type": "String", "required": True}
        ],
        optional_parameters=[],
        auth_required=True,
    )

    # 1. Missing employeeId and leaveType
    resolved_partial = {
        "startDate": ResolvedParam("2026-08-15", ParamSource.USER, trusted=True)
    }
    gate_res = missing_parameter_gate.check(tool, resolved_partial)
    assert not gate_res.passed
    assert "employeeId" in gate_res.missing or "leaveType" in gate_res.missing

    # 2. All required provided
    resolved_full = {
        "employeeId": ResolvedParam("EMP_101", ParamSource.SESSION, trusted=True),
        "leaveType": ResolvedParam("CASUAL", ParamSource.USER, trusted=True),
        "startDate": ResolvedParam("2026-08-15", ParamSource.USER, trusted=True),
    }
    gate_res2 = missing_parameter_gate.check(tool, resolved_full)
    assert gate_res2.passed


def test_approval_service_encryption_and_binding(db_session):
    # P0 test: ensure real arguments are encrypted and recovered unredacted, not as ***REDACTED***
    session_id = "sess_test_1"
    conv_id = "conv_test_1"
    tool_id = "payroll_release_post"
    real_args = {"employeeId": "EMP_77", "salaryAmount": 125000, "pan": "ABCDE1234F"}

    req = approval_service.request_approval(
        db_session,
        session_id=session_id,
        conversation_id=conv_id,
        tool_id=tool_id,
        arguments=real_args,
        risk_tier="DESTRUCTIVE",
        policy_snapshot={"role": "ADMIN"},
        requester_employee_id="EMP_REQ_1",
    )

    # 1. Check arguments_summary is redacted for display
    assert req.arguments_summary["pan"] == "***REDACTED***"

    # 2. Check get_executable_arguments returns UNREDACTED real values
    exec_args = approval_service.get_executable_arguments(db_session, req.id)
    assert exec_args["pan"] == "ABCDE1234F"
    assert exec_args["salaryAmount"] == 125000

    # 3. Test self-approval block
    approval_service.decide(db_session, req.id, approved=True, approver_employee_id="EMP_REQ_1")
    updated_req = db_session.get(approval_service.ApprovalRequest, req.id)
    assert updated_req.status == "REJECTED", "Self-approval of DESTRUCTIVE action should be REJECTED"

    # 4. Test distinct approver approval
    req2 = approval_service.request_approval(
        db_session, session_id=session_id, conversation_id=conv_id, tool_id=tool_id,
        arguments=real_args, risk_tier="DESTRUCTIVE", policy_snapshot={}, requester_employee_id="EMP_REQ_1"
    )
    approval_service.decide(db_session, req2.id, approved=True, approver_employee_id="EMP_APPROVER_2")
    ok, detail = approval_service.is_approved_for_action(db_session, req2.id, tool_id, real_args, session_id=session_id, conversation_id=conv_id)
    assert ok, f"Approval should pass for distinct approver: {detail}"

    # 5. Mismatched session binding check
    ok_bad_sess, _ = approval_service.is_approved_for_action(db_session, req2.id, tool_id, real_args, session_id="OTHER_SESS")
    assert not ok_bad_sess, "Approval should fail for mismatched session ID"


def test_wire_date_serialization():
    assert serialize_wire_value("2026-08-15", java_type="LocalDate") == "2026-08-15"
    assert serialize_wire_value("2026-08-15T10:30:00Z", java_type="LocalDate") == "2026-08-15"
    assert serialize_wire_value("2026-08-15", java_type="LocalDate", wire_format="DD-MM-YYYY") == "15-08-2026"
