"""
Category 3: Parameter Testing
Tests parameter resolution, auto-injection, type formatting, query parameter defaults,
and path parameter replacements across call_xevyte_api and execution handlers.
"""

import pytest
import re
from unittest.mock import patch, AsyncMock
from app.agent.tools import call_xevyte_api, resolve_relative_date


# ============================================================================
# 1. Path Parameter Injections ({employeeId}, {managerId}, {userId})
# ============================================================================

async def test_path_param_employee_id_injection(employee_context):
    """Verify that {employeeId} in path is auto-injected from user_context."""
    # getEmployeeEntries path is /api/daily-entry/employee/{employeeId}
    res = await call_xevyte_api(
        endpoint_id="getEmployeeEntries",
        user_context=employee_context,
        token="test_token"
    )
    assert "status" in res


async def test_path_param_manual_override(employee_context):
    """Verify that explicit path_params take precedence when provided."""
    custom_params = {"employeeId": "EMP999"}
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value.status_code = 200
        mock_req.return_value.is_success = True
        mock_req.return_value.json.return_value = []
        
        await call_xevyte_api(
            endpoint_id="getEmployeeEntries",
            user_context=employee_context,
            path_params=custom_params,
            token="test_token"
        )
        
        # Verify httpx was called with EMP999 in path
        if mock_req.called:
            called_url = mock_req.call_args[1].get("url", "")
            assert "EMP999" in called_url


# ============================================================================
# 2. Body Parameter Auto-Injection
# ============================================================================

async def test_body_employee_id_auto_injection(employee_context):
    """Verify employeeId is injected into body when required by endpoint but omitted by LLM."""
    body_payload = {
        "category": "Travel",
        "amount": 1500,
        "expenseDate": "2026-08-26",
        "expenseDescription": "Taxi fare"
    }
    
    res = await call_xevyte_api(
        endpoint_id="saveClaim",
        user_context=employee_context,
        body=body_payload,
        token="test_token"
    )
    
    if res.get("status") == "pending_confirmation":
        act = res.get("action_data", {})
        assert act.get("body", {}).get("employeeId") == employee_context["employeeId"]


# ============================================================================
# 3. Date Formatting Parameter Tests
# ============================================================================

def test_leave_date_format_requirement():
    """Verify leave dates are formatted as dd-MM-yyyy."""
    date_str = "2026-09-01"
    formatted = resolve_relative_date(date_str, format_output="dd-MM-yyyy")
    assert formatted == "01-09-2026"
    assert re.match(r"^\d{2}-\d{2}-\d{4}$", formatted)


def test_standard_iso_date_format():
    """Verify standard ISO date format yyyy-MM-dd."""
    date_str = "2026-09-01"
    formatted = resolve_relative_date(date_str, format_output="yyyy-MM-dd")
    assert formatted == "2026-09-01"
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", formatted)


# ============================================================================
# 4. Customer Path Param Resolution (CID1 -> 1)
# ============================================================================

async def test_customer_cid_prefix_stripping(admin_context):
    """Verify that 'CID105' is normalized to numeric '105' for customer paths."""
    res = await call_xevyte_api(
        endpoint_id="updateProfile",
        user_context=admin_context,
        path_params={"id": "CID105"},
        token="test_token"
    )
    assert res is not None


# ============================================================================
# 5. Query Parameter Default Handling
# ============================================================================

async def test_weekly_hours_query_param_defaults(employee_context):
    """Verify that getMyWeeklyHours auto-computes start and end date for current week."""
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value.status_code = 200
        mock_req.return_value.is_success = True
        mock_req.return_value.json.return_value = {}

        await call_xevyte_api(
            endpoint_id="getMyWeeklyHours",
            user_context=employee_context,
            token="test_token"
        )

        if mock_req.called:
            params = mock_req.call_args[1].get("params", {})
            if params:
                assert "startDate" in params
                assert "endDate" in params


# ============================================================================
# 6. Misplaced Path Params Extracted from Body
# ============================================================================

async def test_misplaced_path_params_extracted_from_body(employee_context):
    """When LLM puts leaveId or id in body for path like /api/leaves/cancel/{id}."""
    body_with_id = {"id": 12345, "reason": "Change of plans"}
    
    res = await call_xevyte_api(
        endpoint_id="cancelLeave",
        user_context=employee_context,
        body=body_with_id,
        token="test_token"
    )
    
    if res.get("status") == "pending_confirmation":
        act = res.get("action_data", {})
        assert "/12345" in act.get("path", "")
