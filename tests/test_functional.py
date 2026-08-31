"""
Category 1: Functional Testing
Tests every tool, utility, and component for correct output given valid inputs.
"""

import pytest
import os
import json
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from app.agent.tools import (
    APIECatalog,
    search_api_catalog,
    resolve_relative_date,
    search_hr_knowledge_base,
)
from app.agent.engine import is_stalling_response
from app.agent.confirmation import generate_confirmation_token, verify_confirmation_token
from app.auth.jwt_handler import validate_and_extract_token
from app.auth.guardrails import check_input_safety
from app.agent.file_parser import parse_file_for_agent


# ============================================================================
# 1. API Catalog Loading & Structure
# ============================================================================

def test_catalog_load_returns_valid_dict(loaded_catalog):
    """Test that APIECatalog loads the catalog JSON properly."""
    catalog = APIECatalog.load()
    assert isinstance(catalog, dict)
    assert "modules" in catalog
    assert len(catalog["modules"]) > 0


def test_catalog_get_endpoint_success():
    """Test retrieving known endpoints across different modules."""
    ep1 = APIECatalog.get_endpoint("submitEntry")
    assert ep1 is not None
    assert ep1["endpoint_id"] == "submitEntry"
    assert ep1["method"] == "POST"
    assert "/api/daily-entry/submit" in ep1["path"]

    ep2 = APIECatalog.get_endpoint("applyLeave")
    assert ep2 is not None
    assert ep2["endpoint_id"] == "applyLeave"
    assert ep2["method"] == "POST"


def test_catalog_get_endpoint_non_existent():
    """Test get_endpoint returns None for non-existent endpoint IDs."""
    ep = APIECatalog.get_endpoint("completely_fake_endpoint_id_99999")
    assert ep is None


# ============================================================================
# 2. Date Resolution Functional Tests
# ============================================================================

def test_resolve_relative_date_today():
    """Test 'today' resolution in dd-MM-yyyy and yyyy-MM-dd."""
    today = datetime.now().date()
    res_ddmmyyyy = resolve_relative_date("today", format_output="dd-MM-yyyy")
    assert res_ddmmyyyy == today.strftime("%d-%m-%Y")

    res_yyyymmdd = resolve_relative_date("today", format_output="yyyy-MM-dd")
    assert res_yyyymmdd == today.strftime("%Y-%m-%d")


def test_resolve_relative_date_tomorrow():
    """Test 'tomorrow' resolution."""
    tomorrow = datetime.now().date() + timedelta(days=1)
    res = resolve_relative_date("tomorrow", format_output="yyyy-MM-dd")
    assert res == tomorrow.strftime("%Y-%m-%d")


def test_resolve_relative_date_days_offset():
    """Test relative offset like '5 days'."""
    target = datetime.now().date() + timedelta(days=5)
    res = resolve_relative_date("5 days", format_output="yyyy-MM-dd")
    assert res == target.strftime("%Y-%m-%d")


def test_resolve_relative_date_weeks_offset():
    """Test relative offset like '2 weeks'."""
    target = datetime.now().date() + timedelta(days=14)
    res = resolve_relative_date("2 weeks", format_output="yyyy-MM-dd")
    assert res == target.strftime("%Y-%m-%d")


def test_resolve_relative_date_explicit_date():
    """Test standard date string parsing."""
    res = resolve_relative_date("2026-10-15", format_output="dd-MM-yyyy")
    assert res == "15-10-2026"


def test_resolve_relative_date_weekdays():
    """Test day of week resolution (e.g. 'friday', 'this friday', 'next monday', 'mon', 'tue', etc.)."""
    today = datetime.now().date()
    days_map = {
        "monday": 0, "mon": 0,
        "tuesday": 1, "tue": 1,
        "wednesday": 2, "wed": 2,
        "thursday": 3, "thu": 3, "thrusday": 3,
        "friday": 4, "fri": 4,
        "saturday": 5, "sat": 5,
        "sunday": 6, "sun": 6
    }
    
    # Test "friday" / "fri"
    fri_ahead = (days_map["friday"] - today.weekday()) % 7
    expected_fri = today + timedelta(days=fri_ahead)
    assert resolve_relative_date("friday", format_output="dd-MM-yyyy") == expected_fri.strftime("%d-%m-%Y")
    assert resolve_relative_date("fri", format_output="dd-MM-yyyy") == expected_fri.strftime("%d-%m-%Y")
    assert resolve_relative_date("this fri", format_output="dd-MM-yyyy") == expected_fri.strftime("%d-%m-%Y")
    assert resolve_relative_date("for friday", format_output="dd-MM-yyyy") == expected_fri.strftime("%d-%m-%Y")

    # Test "mon", "tue", "wed", "thu", "thrusday", "sat", "sun"
    for day_alias in ("mon", "tue", "wed", "thu", "thrusday", "sat", "sun"):
        t_day = days_map[day_alias]
        d_ahead = (t_day - today.weekday()) % 7
        exp = today + timedelta(days=d_ahead)
        assert resolve_relative_date(day_alias, format_output="dd-MM-yyyy") == exp.strftime("%d-%m-%Y")

    # Test "next day", "day before day", "day after tomorrow"
    assert resolve_relative_date("next day", format_output="dd-MM-yyyy") == (today + timedelta(days=1)).strftime("%d-%m-%Y")
    assert resolve_relative_date("day before day", format_output="dd-MM-yyyy") == (today - timedelta(days=1)).strftime("%d-%m-%Y")
    assert resolve_relative_date("day after tomorrow", format_output="dd-MM-yyyy") == (today + timedelta(days=2)).strftime("%d-%m-%Y")

    # Test formats: dd/mm/yyyy, yyyy/mm/dd, mm/yyyy/dd
    assert resolve_relative_date("28/08/2026", format_output="dd-MM-yyyy") == "28-08-2026"
    assert resolve_relative_date("2026/08/28", format_output="dd-MM-yyyy") == "28-08-2026"
    assert resolve_relative_date("08/2026/28", format_output="dd-MM-yyyy") == "28-08-2026"


def test_format_action_summary():
    """Test action summary markdown generation for confirmation node."""
    from app.agent.engine import format_action_summary
    action_data = {
        "endpoint_id": "applyLeave",
        "method": "POST",
        "path": "/api/leaves/apply",
        "body": {
            "type": "Sick Leave",
            "startDate": "28-08-2026",
            "endDate": "28-08-2026",
            "reason": "stomach pain"
        }
    }
    summary = format_action_summary(action_data)
    assert "Apply Leave" in summary
    assert "Sick Leave" in summary
    assert "28-08-2026" in summary
    assert "stomach pain" in summary
    assert "Approve" in summary


# ============================================================================
# 3. Confirmation Token Generation & Verification
# ============================================================================

def test_confirmation_token_roundtrip(employee_claims):
    """Test token encryption and decryption integrity."""
    action_data = {
        "endpoint_id": "applyLeave",
        "method": "POST",
        "path": "/api/leaves/apply",
        "body": {"leaveType": "Casual", "startDate": "01-09-2026", "endDate": "02-09-2026"}
    }
    emp_id = employee_claims["employeeId"]
    
    token = generate_confirmation_token(action_data, emp_id)
    assert isinstance(token, str)
    assert len(token) > 20

    verified_action = verify_confirmation_token(token, emp_id)
    assert verified_action["endpoint_id"] == "applyLeave"
    assert verified_action["body"]["leaveType"] == "Casual"


# ============================================================================
# 4. Guardrails Functional Verification
# ============================================================================

def test_guardrails_benign_inputs():
    """Test that legitimate HR queries pass the safety guardrails."""
    assert check_input_safety("Can I apply for casual leave next week?") is True
    assert check_input_safety("What is my remaining expense reimbursement balance?") is True
    assert check_input_safety("Show my attendance records for August 2026") is True
    assert check_input_safety("I need to update my emergency contact number") is True


# ============================================================================
# 5. Stalling Text Detection Functional Verification
# ============================================================================

def test_stalling_detection():
    """Verify that placeholder/stalling phrases are accurately flagged."""
    assert is_stalling_response("Please hold on for a moment while I fetch that.") is True
    assert is_stalling_response("Let me first check your leave balance...") is True
    assert is_stalling_response("Give me a moment to look into this.") is True
    assert is_stalling_response("Hold on sec, retrieving that information.") is True
    assert is_stalling_response("Your leave balance is 14 days Casual Leave.") is False
    assert is_stalling_response("I have submitted your attendance punch in.") is False


# ============================================================================
# 6. JWT Extraction Functional Verification
# ============================================================================

def test_jwt_extraction_valid(employee_token, employee_claims):
    """Test claims extraction from valid JWT."""
    ctx = validate_and_extract_token(employee_token)
    assert ctx is not None
    assert ctx["employeeId"] == employee_claims["employeeId"]
    assert ctx["role"] == "EMPLOYEE"
    assert ctx["sub"] == employee_claims["sub"]


# ============================================================================
# 7. File Parser Functional Tests
# ============================================================================

def test_parse_csv_file():
    """Test parsing CSV files into text context for agent."""
    csv_bytes = b"firstName,lastName,email\nJohn,Doe,john@example.com\nJane,Smith,jane@example.com"
    res = parse_file_for_agent("employees.csv", csv_bytes, "text/csv")
    assert res["type"] == "document"
    assert res["filename"] == "employees.csv"
    assert "john@example.com" in res["data"]


def test_parse_image_file():
    """Test parsing image files into base64 data uri context."""
    img_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    res = parse_file_for_agent("receipt.png", img_bytes, "image/png")
    assert res["type"] == "image"
    assert res["filename"] == "receipt.png"
    assert res["data"].startswith("data:image/png;base64,")
