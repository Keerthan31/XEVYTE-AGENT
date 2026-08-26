"""
Category 12: User Acceptance Testing (UAT)
Simulates end-to-end user journeys for:
- Standard Employees (Punch in, apply leave, claim expense, raise ticket)
- Managers (Approve leave, review team tickets, inspect allocations)
- HR Admins (Applicant tracking, employee onboarding, asset allocation, payroll)
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from app.agent.tools import call_xevyte_api, search_api_catalog


# ============================================================================
# 1. Employee Journey UAT
# ============================================================================

async def test_uat_employee_daily_workflow(employee_context):
    """
    UAT Scenario 1: Employee Daily Workflow
    1. Employee punches in for attendance
    2. Employee checks leave balance
    3. Employee applies for leave
    4. Employee submits an expense claim
    """
    # Step 1: Punch In
    punch_res = await call_xevyte_api(
        endpoint_id="submitEntry",
        user_context=employee_context,
        body={"workLocation": "Office"},
        token="test_token"
    )
    assert "status" in punch_res

    # Step 2: Check Leave Balance
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_success = True
    mock_resp.json.return_value = {
        "leaveBalances": [{"leaveType": "Casual", "available": 10}]
    }

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_resp):
        balance_res = await call_xevyte_api(
            endpoint_id="getDetailedLeaveBalance",
            user_context=employee_context,
            token="test_token"
        )
        assert "status" in balance_res

    # Step 3: Apply Leave
    with patch("app.agent.tools.WorkflowHelpers.collect_leave_data", new_callable=AsyncMock) as mock_leave:
        mock_leave.return_value = {
            "payload": {"type": "Casual", "startDate": "01-09-2026", "endDate": "02-09-2026", "reason": "Family function"}
        }
        leave_res = await call_xevyte_api(
            endpoint_id="applyLeave",
            user_context=employee_context,
            body={"type": "Casual", "startDate": "01-09-2026", "endDate": "02-09-2026", "reason": "Family function"},
            token="test_token"
        )
        assert leave_res.get("status") == "pending_confirmation"

    # Step 4: Submit Expense Claim
    claim_res = await call_xevyte_api(
        endpoint_id="saveClaim",
        user_context=employee_context,
        body={"category": "Travel", "amount": 800, "expenseDate": "2026-08-26", "expenseDescription": "Client visit"},
        token="test_token"
    )
    assert "status" in claim_res


# ============================================================================
# 2. Manager Approval Journey UAT
# ============================================================================

async def test_uat_manager_approval_workflow(manager_context):
    """
    UAT Scenario 2: Manager Workflow
    1. Manager reviews pending team leave requests
    2. Manager approves a leave request
    """
    # Step 1: Fetch Pending Leaves
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_success = True
    mock_resp.json.return_value = [
        {"id": 101, "employeeName": "John Doe", "leaveType": "Casual", "totalDays": 2}
    ]

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_resp):
        pending_res = await call_xevyte_api(
            endpoint_id="getPendingLeavesForManager",
            user_context=manager_context,
            token="test_token"
        )
        assert "status" in pending_res

    # Step 2: Approve Leave
    approve_res = await call_xevyte_api(
        endpoint_id="approveLeave",
        user_context=manager_context,
        body={"leaveRequestId": 101, "approverId": manager_context["employeeId"], "role": "MANAGER", "action": "Approve"},
        token="test_token"
    )
    assert approve_res.get("status") == "pending_confirmation"


# ============================================================================
# 3. HR Admin Onboarding & Governance Journey UAT
# ============================================================================

async def test_uat_hr_admin_onboarding_and_asset_workflow(admin_context):
    """
    UAT Scenario 3: HR Admin Workflow
    1. View Pre-onboarding applicants
    2. Onboard new employee
    3. Register asset
    """
    # Step 1: Pre-onboarding applicants
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_success = True
    mock_resp.json.return_value = [{"applicantId": 50, "firstName": "Alice", "position": "Engineer"}]

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_resp):
        app_res = await call_xevyte_api(
            endpoint_id="getApplicants",
            user_context=admin_context,
            token="test_token"
        )
        assert "status" in app_res

    # Step 2: Onboard Single Employee
    onboard_res = await call_xevyte_api(
        endpoint_id="onboardSingleEmployee",
        user_context=admin_context,
        body={
            "firstName": "Alice", "lastName": "Wonder", "designation": "Developer",
            "joiningDate": "2026-09-01", "workLocation": "Bangalore", "employeeId": "EMP050",
            "email": "alice@xevyte.com", "gender": "Female", "bloodGroup": "O+",
            "dateOfBirth": "1998-05-15", "aadhaarNo": "123456789012", "panNo": "ABCDE1234F"
        },
        token="test_token"
    )
    assert onboard_res.get("status") == "pending_confirmation"

    # Step 3: Register Asset
    asset_res = await call_xevyte_api(
        endpoint_id="createAsset",
        user_context=admin_context,
        body={"assetName": "MacBook Pro M3", "category": "Laptops", "serialNumber": "MBP-98765"},
        token="test_token"
    )
    assert asset_res.get("status") == "pending_confirmation"
