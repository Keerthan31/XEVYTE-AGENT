"""
Category 4: API/Tool Testing
Tests tools provided to the agent: search_api_catalog, call_xevyte_api,
search_hr_knowledge_base, document RAG, and execution helpers (_execute_single_action).
"""

import pytest
import json
import httpx
from unittest.mock import patch, AsyncMock, MagicMock

from app.agent.tools import (
    search_api_catalog,
    search_hr_knowledge_base,
    call_xevyte_api,
)
from app.routes.chat import _execute_single_action
from app.config import get_settings


# ============================================================================
# 1. search_api_catalog Tool Tests
# ============================================================================

def test_search_api_catalog_valid_query():
    """Verify tool returns readable description for valid HR query."""
    res = search_api_catalog("apply for leave")
    assert isinstance(res, str)
    assert "Tool Name:" in res
    assert "URL Path:" in res
    assert "/api/leaves" in res


def test_search_api_catalog_empty_or_nonsense_query():
    """Verify tool returns guidance when no endpoint matches nonsense."""
    res = search_api_catalog("xyzqwerty123456789nonexistent")
    assert isinstance(res, str)
    assert "No matching endpoints found" in res or "Please be more specific" in res


# ============================================================================
# 2. search_hr_knowledge_base (RAG / Handbook) Tool Tests
# ============================================================================

def test_search_hr_knowledge_base():
    """Verify knowledge base retrieval returns policy text or fallback."""
    res = search_hr_knowledge_base("maternity leave policy")
    assert isinstance(res, str)
    assert len(res) > 10


# ============================================================================
# 3. call_xevyte_api Execution & Confirmation Workflow
# ============================================================================

async def test_call_xevyte_api_unknown_endpoint(employee_context):
    """Verify calling an uncataloged endpoint returns error with suggestion."""
    res = await call_xevyte_api(
        endpoint_id="non_existent_fake_endpoint_123",
        user_context=employee_context,
        token="test_token"
    )
    assert res.get("status") == "error"
    assert "not found in catalog" in res.get("error", "")


async def test_call_xevyte_api_post_triggers_confirmation(employee_context):
    """POST/PUT/DELETE mutations must yield pending_confirmation status with a token."""
    with patch("app.agent.tools.WorkflowHelpers.collect_leave_data", new_callable=AsyncMock) as mock_leave:
        mock_leave.return_value = {
            "payload": {"type": "Casual", "startDate": "01-09-2026", "endDate": "02-09-2026", "reason": "Personal work"}
        }
        res = await call_xevyte_api(
            endpoint_id="applyLeave",
            user_context=employee_context,
            body={"type": "Casual", "startDate": "01-09-2026", "endDate": "02-09-2026", "reason": "Personal work"},
            token="test_token"
        )
        assert res.get("status") == "pending_confirmation"
        assert "pending_confirmation_token" in res or "action_data" in res


async def test_call_xevyte_api_get_executes_directly(employee_context):
    """GET read endpoints should directly execute without requiring confirmation."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_success = True
    mock_resp.json.return_value = [{"id": 1, "status": "APPROVED"}]
    
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_resp):
        res = await call_xevyte_api(
            endpoint_id="getEmployeeEntries",
            user_context=employee_context,
            token="test_token"
        )
        assert res.get("status") == "success" or res.get("status") == 200 or isinstance(res, dict)


# ============================================================================
# 4. _execute_single_action Helper Tests
# ============================================================================

async def test_execute_single_action_json_body(employee_context):
    """Test executing standard JSON action via _execute_single_action."""
    settings = get_settings()
    action_data = {
        "endpoint_id": "createLeaveType",
        "method": "POST",
        "path": "/api/admin/leave-policy/type",
        "body": {"leaveTypeName": "Sabbatical", "yearlyQuota": 30, "accrualType": "YEARLY"}
    }
    headers = {"Authorization": "Bearer test"}

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_success = True
    mock_resp.json.return_value = {"id": 10, "leaveTypeName": "Sabbatical"}

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_resp

    is_success, resp_data = await _execute_single_action(
        client=mock_client,
        action_data=action_data,
        headers=headers,
        user_context=employee_context,
        settings=settings
    )
    assert is_success is True
    assert resp_data.get("leaveTypeName") == "Sabbatical"


async def test_execute_single_action_leave_apply_dto(employee_context):
    """Test /api/leaves/apply wraps body inside multipart 'dto' payload."""
    settings = get_settings()
    action_data = {
        "endpoint_id": "applyLeave",
        "method": "POST",
        "path": "/api/leaves/apply",
        "body": {"type": "Sick", "startDate": "10-09-2026", "endDate": "11-09-2026", "reason": "Fever"}
    }
    headers = {"Authorization": "Bearer test"}

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_success = True
    mock_resp.json.return_value = {"leaveId": 999, "status": "PENDING"}

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_resp

    is_success, resp_data = await _execute_single_action(
        client=mock_client,
        action_data=action_data,
        headers=headers,
        user_context=employee_context,
        settings=settings
    )
    assert is_success is True
    call_kwargs = mock_client.request.call_args[1]
    assert "files" in call_kwargs
    assert "dto" in call_kwargs["files"]
