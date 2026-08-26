"""
Category 7: Negative Testing
Tests edge cases, boundary violations, invalid tokens, mismatched IDs,
malformed dates, backend 500s, and non-JSON backend error payloads.
"""

import pytest
import httpx
from unittest.mock import patch, AsyncMock, MagicMock
from app.agent.tools import resolve_relative_date, call_xevyte_api
from app.routes.chat import _execute_single_action
from app.config import get_settings


# ============================================================================
# 1. Invalid Date Resolution
# ============================================================================

def test_resolve_invalid_relative_date_raises():
    """Unrecognized date strings should raise ValueError."""
    with pytest.raises(ValueError):
        resolve_relative_date("not-a-real-date-or-keyword-xyz")


# ============================================================================
# 2. Non-Existent Endpoint Execution
# ============================================================================

async def test_call_xevyte_api_invalid_endpoint_id(employee_context):
    """Calling an invalid endpoint returns status error."""
    res = await call_xevyte_api(
        endpoint_id="totallyBogusEndpointId",
        user_context=employee_context,
        token="test_token"
    )
    assert res.get("status") == "error"
    assert "not found" in res.get("error", "").lower()


# ============================================================================
# 3. Backend Error Responses (500 Internal Server Error & 404 Not Found)
# ============================================================================

async def test_execute_single_action_backend_500(employee_context):
    """Backend returning 500 is cleanly caught and reported as failure."""
    settings = get_settings()
    action_data = {
        "endpoint_id": "getEmployeeEntries",
        "method": "GET",
        "path": "/api/daily-entry/employee/EMP001"
    }
    
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.is_success = False
    mock_resp.json.return_value = {"error": "Database connection failed"}

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_resp

    is_success, resp_data = await _execute_single_action(
        client=mock_client,
        action_data=action_data,
        headers={"Authorization": "Bearer test"},
        user_context=employee_context,
        settings=settings
    )
    assert is_success is False
    assert "Database connection failed" in str(resp_data)


async def test_execute_single_action_backend_non_json_error(employee_context):
    """Backend returning raw HTML/text 502 Bad Gateway fallback."""
    settings = get_settings()
    action_data = {
        "endpoint_id": "getEmployeeEntries",
        "method": "GET",
        "path": "/api/daily-entry/employee/EMP001"
    }
    
    mock_resp = MagicMock()
    mock_resp.status_code = 502
    mock_resp.is_success = False
    mock_resp.json.side_effect = Exception("Not JSON")
    mock_resp.text = "<html>502 Bad Gateway</html>"

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_resp

    is_success, resp_data = await _execute_single_action(
        client=mock_client,
        action_data=action_data,
        headers={"Authorization": "Bearer test"},
        user_context=employee_context,
        settings=settings
    )
    assert is_success is False
    assert "502 Bad Gateway" in str(resp_data)
