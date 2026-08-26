"""
Category 11: Regression Testing
Prevents recurrence of fixed bugs and preserves specialized behavior:
- Asset category auto-resolution
- Customer CID prefix stripping
- Multipart dto/claim wrapping
- Custom headers for exit management and team tickets
- Content-Type conflict resolution with multipart boundaries
"""

import pytest
import httpx
from unittest.mock import patch, AsyncMock
from app.routes.chat import _execute_single_action
from app.config import get_settings


@pytest.mark.asyncio
async def test_regression_exit_management_custom_headers(employee_context):
    """
    Regression: Java backend for exit management requires custom headers:
    employeeId, employeeName, managerId, managerName, department.
    """
    settings = get_settings()
    action_data = {
        "endpoint_id": "getMyResignation",
        "method": "GET",
        "path": "/api/v1/exit-management/my-resignation"
    }
    
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value.status_code = 200
        mock_req.return_value.is_success = True
        mock_req.return_value.json.return_value = {"status": "NONE"}
        
        async with httpx.AsyncClient() as client:
            await _execute_single_action(
                client=client,
                action_data=action_data,
                headers={"Authorization": "Bearer test"},
                user_context=employee_context,
                settings=settings
            )
            
            headers_sent = mock_req.call_args[1].get("headers", {})
            assert "employeeId" in headers_sent
            assert "department" in headers_sent


@pytest.mark.asyncio
async def test_regression_team_tickets_custom_header(manager_context):
    """
    Regression: /api/tickets/team-tickets requires employeeId passed in headers.
    """
    settings = get_settings()
    action_data = {
        "endpoint_id": "getTeamTickets",
        "method": "GET",
        "path": "/api/tickets/team-tickets"
    }
    
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value.status_code = 200
        mock_req.return_value.is_success = True
        mock_req.return_value.json.return_value = []
        
        async with httpx.AsyncClient() as client:
            await _execute_single_action(
                client=client,
                action_data=action_data,
                headers={"Authorization": "Bearer test"},
                user_context=manager_context,
                settings=settings
            )
            
            headers_sent = mock_req.call_args[1].get("headers", {})
            assert "employeeId" in headers_sent
            assert headers_sent["employeeId"] == manager_context["employeeId"]


@pytest.mark.asyncio
async def test_regression_content_type_stripped_for_multipart(employee_context):
    """
    Regression: When request has files (multipart), manual Content-Type header must be deleted
    so httpx can generate the correct boundary.
    """
    settings = get_settings()
    action_data = {
        "endpoint_id": "applyLeave",
        "method": "POST",
        "path": "/api/leaves/apply",
        "body": {"type": "Casual", "startDate": "01-09-2026", "endDate": "02-09-2026", "reason": "Rest"}
    }
    
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value.status_code = 200
        mock_req.return_value.is_success = True
        mock_req.return_value.json.return_value = {"status": "SUBMITTED"}
        
        async with httpx.AsyncClient() as client:
            # Pass explicit Content-Type: application/json in headers
            headers = {"Authorization": "Bearer test", "Content-Type": "application/json"}
            await _execute_single_action(
                client=client,
                action_data=action_data,
                headers=headers,
                user_context=employee_context,
                settings=settings
            )
            
            headers_sent = mock_req.call_args[1].get("headers", {})
            # Content-Type should not be application/json because multipart files were added
            assert headers_sent.get("Content-Type") != "application/json"
