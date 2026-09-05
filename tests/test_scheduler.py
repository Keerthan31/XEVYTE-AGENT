import pytest
import httpx
from unittest.mock import patch, MagicMock
from app.scheduler.tasks import run_morning_checkin_reminders, run_evening_checkout_reminders

@pytest.mark.asyncio
async def test_run_morning_checkin_reminders_uses_correct_endpoint():
    with patch("app.scheduler.tasks.fetch_active_employees") as mock_fetch, \
         patch("app.scheduler.tasks.is_holiday_or_weekend") as mock_holiday, \
         patch("httpx.AsyncClient.get") as mock_get:

        # Setup mock active employees
        mock_fetch.return_value = [
            {"employeeId": "test_emp", "workEmail": "test@example.com", "name": "Test Emp"}
        ]

        # Setup mock holiday check (not a holiday)
        mock_holiday.return_value = (False, "Working Day")

        # Setup mock get response for attendance check
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = [] # no entries means not checked in
        mock_get.return_value = mock_response

        # Call the task with force=True to ensure it runs
        await run_morning_checkin_reminders(force=True)

        # Verify the correct endpoint was called
        called_args = mock_get.call_args_list
        # We expect a call to the attendance endpoint
        # The mock gets called for other things, but let's just check one of the calls matches our expected URL structure

        assert any(
            "/api/daily-entry/employee/test_emp" in call.args[0]
            for call in called_args
        ), f"Expected endpoint /api/daily-entry/employee/test_emp to be called. Calls were: {called_args}"


@pytest.mark.asyncio
async def test_run_evening_checkout_reminders_uses_correct_endpoint():
    with patch("app.scheduler.tasks.fetch_active_employees") as mock_fetch, \
         patch("app.scheduler.tasks.is_holiday_or_weekend") as mock_holiday, \
         patch("httpx.AsyncClient.get") as mock_get:

        # Setup mock active employees
        mock_fetch.return_value = [
            {"employeeId": "test_emp", "workEmail": "test@example.com", "name": "Test Emp"}
        ]

        # Setup mock holiday check (not a holiday)
        mock_holiday.return_value = (False, "Working Day")

        # Setup mock get response for attendance check
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = []
        mock_get.return_value = mock_response

        # Call the task with force=True to ensure it runs
        await run_evening_checkout_reminders(force=True)

        # Verify the correct endpoint was called
        called_args = mock_get.call_args_list
        assert any(
            "/api/daily-entry/employee/test_emp" in call.args[0]
            for call in called_args
        ), f"Expected endpoint /api/daily-entry/employee/test_emp to be called. Calls were: {called_args}"
