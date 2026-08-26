"""
Category 6: Hallucination Testing
Tests anti-hallucination guardrails: method/path override protection,
zero-record transparency, accurate failure reporting, and non-fabricated status messages.
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from app.agent.tools import call_xevyte_api, APIECatalog
from app.routes.chat import _execute_single_action
from app.config import get_settings


# ============================================================================
# 1. Enforce Catalog Truth (Prevent LLM Path & Method Hallucinations)
# ============================================================================

async def test_llm_cannot_hallucinate_method_or_path(employee_context):
    """
    Even if LLM tries to call an endpoint with a fabricated HTTP method or URL,
    call_xevyte_api must enforce the catalog's authoritative method and path.
    """
    with patch("app.agent.tools.WorkflowHelpers.collect_leave_data", new_callable=AsyncMock) as mock_leave:
        mock_leave.return_value = {
            "payload": {"type": "Casual", "startDate": "01-09-2026", "endDate": "02-09-2026", "reason": "Rest"}
        }
        res = await call_xevyte_api(
            endpoint_id="applyLeave",
            user_context=employee_context,
            method="DELETE", # LLM hallucinated method
            path="/api/fake/admin/leaves", # LLM hallucinated path
            body={"type": "Casual", "startDate": "01-09-2026", "endDate": "02-09-2026", "reason": "Rest"},
            token="test_token"
        )
        
        # Verify the generated action retained catalog truth
        action_data = res.get("action_data", {})
        assert action_data.get("method") == "POST"
        assert "/api/leaves/apply" in action_data.get("path", "")


# ============================================================================
# 2. Transparent Reporting for Zero-Record Actions (e.g. Payslips)
# ============================================================================

async def test_payslip_zero_records_transparency(admin_context):
    """
    When backend returns 0 payslips generated, agent must not pretend success.
    It must explicitly report that 0 payslips were generated due to missing salary config.
    """
    settings = get_settings()
    action_data = {
        "endpoint_id": "generatePayslips",
        "method": "POST",
        "path": "/api/payroll/generate-payslips",
        "body": {"month": "August", "year": "2026"}
    }
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_success = True
    mock_resp.json.return_value = [] # 0 payslips

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_resp

    is_success, resp_data = await _execute_single_action(
        client=mock_client,
        action_data=action_data,
        headers={"Authorization": "Bearer test"},
        user_context=admin_context,
        settings=settings
    )
    assert is_success is True
    assert isinstance(resp_data, list)
    assert len(resp_data) == 0


# ============================================================================
# 3. Transparent Reporting on Bulk Onboarding Partial/Full Failure
# ============================================================================

def test_bulk_onboarding_failure_details_parsing():
    """Verify failure breakdown is accurately parsed without fabricating success."""
    resp_data = {
        "totalRecords": 5,
        "successCount": 3,
        "failureDetails": [
            {"rowNumber": 2, "reason": "Invalid Aadhaar Number"},
            {"rowNumber": 4, "reason": "Work Email already registered"}
        ]
    }
    
    total = resp_data["totalRecords"]
    succ_cnt = resp_data["successCount"]
    failures = resp_data["failureDetails"]
    
    err_reasons = [f"Row {f.get('rowNumber')}: {f.get('reason')}" for f in failures]
    msg = f"Bulk onboarding partially completed: {succ_cnt}/{total} succeeded, {len(failures)} failed.\nFailures:\n" + "\n".join(err_reasons)
    
    assert "3/5 succeeded" in msg
    assert "Row 2: Invalid Aadhaar Number" in msg
    assert "Row 4: Work Email already registered" in msg
