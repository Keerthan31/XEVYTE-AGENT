"""
HRMS Tool functions — each one calls a Xevyte Connect REST API endpoint.
All tools receive the JWT token (from Scaloz IAM) via a shared context
that is injected by the agent before each tool call.
"""

import httpx
import logging
from contextvars import ContextVar
from datetime import datetime, date
from langchain_core.tools import tool
from config import XEVYTE_API_BASE

logger = logging.getLogger(__name__)

# ─── Thread-safe token store (per-request, set by agent.py) ───────────────────
_current_token: ContextVar[str] = ContextVar("_current_token", default="")
_current_employee_id: ContextVar[str] = ContextVar("_current_employee_id", default="")


def set_session(token: str, employee_id: str):
    _current_token.set(token)
    _current_employee_id.set(employee_id)


def _auth_headers():
    """Auth-only headers — use for JSON requests (httpx sets Content-Type itself)."""
    return {"Authorization": f"Bearer {_current_token.get()}"}


def _json_headers():
    """Headers for JSON body requests."""
    return {
        "Authorization": f"Bearer {_current_token.get()}",
        "Content-Type": "application/json",
    }


def _base():
    return XEVYTE_API_BASE


# ─── Date helpers ─────────────────────────────────────────────────────────────
_DATE_FORMATS = [
    "%d-%m-%Y",   # 27-07-2026  ← backend requires this
    "%Y-%m-%d",   # 2026-07-27
    "%d/%m/%Y",   # 27/07/2026
    "%m/%d/%Y",   # 07/27/2026
    "%d-%m-%y",   # 27-07-26
    "%B %d, %Y",  # July 27, 2026
    "%d %B %Y",   # 27 July 2026
]


def _to_backend_date(date_str: str) -> str:
    """
    Accept any common date format from the LLM and return dd-MM-yyyy
    which is what the Xevyte backend's @JsonFormat annotation expects.
    """
    date_str = date_str.strip().lower()
    
    # Handle natural language dates from LLM
    if date_str == "today":
        return datetime.now().strftime("%d-%m-%Y")
    if date_str == "tomorrow":
        from datetime import timedelta
        return (datetime.now() + timedelta(days=1)).strftime("%d-%m-%Y")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(date_str, fmt).strftime("%d-%m-%Y")
        except ValueError:
            continue
    # Last resort — return as-is and let the backend error naturally
    logger.warning(f"Could not parse date: {date_str}")
    return date_str


def _fmt_error(resp: httpx.Response, action: str) -> str:
    """Return a clear error string with the backend's actual message."""
    try:
        body = resp.json()
        msg = body.get("message") or body.get("error") or body.get("detail") or str(body)
    except Exception:
        msg = resp.text[:400] or "(no body)"
    return (
        f"❌ {action} failed (HTTP {resp.status_code}).\n"
        f"Backend says: {msg}\n"
        f"Please check the details and try again."
    )


# ─── 1. Get leave balance (detailed) ─────────────────────────────────────────
@tool
def get_leave_balance() -> str:
    """
    Fetch the current leave balance for the logged-in employee.
    Returns each leave type with granted, consumed, and remaining days.
    """
    url = f"{_base()}/api/leaves/balance/details/{_current_employee_id.get()}"
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(url, headers=_auth_headers())
        if resp.status_code == 200:
            data = resp.json()
            if not data:
                return "No leave balance records found."
            return str(data)
        return _fmt_error(resp, "Get leave balance")
    except httpx.ConnectError:
        return "❌ Cannot connect to Xevyte backend. Make sure it is running."
    except Exception as e:
        return f"❌ Unexpected error: {e}"


# ─── 2. Get leave history ─────────────────────────────────────────────────────
@tool
def get_leave_history() -> str:
    """
    Get the full leave request history for the logged-in employee,
    including status (Pending, Approved, Rejected, Cancelled).
    """
    url = f"{_base()}/api/leaves/employee/{_current_employee_id.get()}"
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(url, headers=_auth_headers())
        if resp.status_code == 200:
            data = resp.json()
            if not data:
                return "No leave requests found."
            return str(data[:20])
        return _fmt_error(resp, "Get leave history")
    except httpx.ConnectError:
        return "❌ Cannot connect to Xevyte backend."
    except Exception as e:
        return f"❌ Unexpected error: {e}"


# ─── 3. Apply for leave ───────────────────────────────────────────────────────
@tool
def apply_leave(
    leave_type: str,
    start_date: str,
    end_date: str,
    reason: str,
    half_day: bool = False,
) -> str:
    """
    Apply for leave on behalf of the logged-in employee.

    Args:
        leave_type: Exact leave type name exactly as it appears in the leave balance response (e.g. "EL", "SL", "Optional"). Do not use hardcoded mappings like "Sick Leave" if the balance says "SL".
        start_date: Start date — any common format e.g. "27-07-2026" or "2026-07-27"
        end_date:   End date — any common format
        reason:     Reason for leave
        half_day:   True only for a half-day leave
    """
    # Normalize dates to dd-MM-yyyy which the backend's @JsonFormat requires
    try:
        sd_str = _to_backend_date(start_date)
        ed_str = _to_backend_date(end_date)
        sd = datetime.strptime(sd_str, "%d-%m-%Y").date()
        ed = datetime.strptime(ed_str, "%d-%m-%Y").date()

        if ed < sd:
            return "❌ End date cannot be before start date."
    except Exception as e:
        return f"❌ Invalid date format: {e}. Please use a clear date like '27-07-2026'."

    # Auto-correct common LLM leave type hallucinations based on known DB types
    l_type_lower = leave_type.lower()
    if "optional" in l_type_lower:
        leave_type = "Optional"
    elif "sick" in l_type_lower or l_type_lower == "sl":
        leave_type = "SL"
    elif "earned" in l_type_lower or l_type_lower == "el":
        leave_type = "EL"
    elif "casual" in l_type_lower or l_type_lower == "cl":
        leave_type = "CL"
    elif "lop" in l_type_lower or "loss" in l_type_lower:
        leave_type = "LOP"

    payload = {
        "employeeId": _current_employee_id.get(),
        "type": leave_type,
        "startDate": sd_str,   # dd-MM-yyyy as required by @JsonFormat
        "endDate": ed_str,
        "reason": reason,
        "halfDay": half_day,
        # totalDays is recalculated server-side; we omit it to avoid conflicts
    }

    import json
    url = f"{_base()}/api/leaves/apply"
    
    # Spring expects @RequestPart("dto") to be application/json
    files = {
        "dto": (None, json.dumps(payload), "application/json")
    }
    
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.post(url, files=files, headers=_auth_headers())
        if resp.status_code in (200, 201):
            data = resp.json()
            ref = data.get("referenceId") or data.get("id") or "N/A"
            return (
                f"✅ Leave applied successfully!\n"
                f"Reference ID : {ref}\n"
                f"Type         : {data.get('type', leave_type)}\n"
                f"Dates        : {sd_str} → {ed_str}\n"
                f"Days         : {data.get('totalDays', '?')}\n"
                f"Status       : {data.get('status', 'Pending')}"
            )
        return _fmt_error(resp, "Apply leave")
    except httpx.ConnectError:
        return "❌ Cannot connect to Xevyte backend."
    except Exception as e:
        return f"❌ Unexpected error: {e}"


# ─── 4. Cancel leave ──────────────────────────────────────────────────────────
@tool
def cancel_leave(leave_id_or_ref: str) -> str:
    """
    Cancel a pending leave request. You can provide either the numeric ID or the string Reference ID (e.g., 'SCA-LV-2026-000043').
    """
    leave_id = str(leave_id_or_ref).strip()
    
    # If the provided ID is not strictly numeric, we must look up the numeric ID
    if not leave_id.isdigit():
        history_url = f"{_base()}/api/leaves/employee/{_current_employee_id.get()}"
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.get(history_url, headers=_auth_headers())
            if resp.status_code == 200:
                history_data = resp.json()
                found_id = None
                for req in history_data:
                    if req.get("referenceId") == leave_id or str(req.get("id")) == leave_id:
                        found_id = req.get("id")
                        break
                if not found_id:
                    return f"❌ Could not find a leave request matching reference '{leave_id}'."
                leave_id = str(found_id)
            else:
                return f"❌ Could not look up leave reference '{leave_id}' (HTTP {resp.status_code})."
        except Exception as e:
            return f"❌ Error looking up leave reference: {e}"

    url = f"{_base()}/api/leaves/cancel/{leave_id}"
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.put(url, headers=_auth_headers())
        if resp.status_code in (200, 204):
            return f"✅ Leave request {leave_id_or_ref} cancelled successfully."
        return _fmt_error(resp, f"Cancel leave {leave_id_or_ref}")
    except httpx.ConnectError:
        return "❌ Cannot connect to Xevyte backend."
    except Exception as e:
        return f"❌ Unexpected error: {e}"



# ─── 6. Raise a grievance ─────────────────────────────────────────────────────

@tool
def raise_grievance(
    subject: str,
    description: str,
    category: str = "General",
    grievance_type: str = "",
) -> str:
    """
    Raise a grievance (can be anonymous).

    Args:
        subject:        Short subject/title of the grievance (max 150 chars)
        description:    Full detailed description of the issue
        category:       One of: "Harassment", "Payroll", "Work Environment",
                        "Policy Violation", "Discrimination", "General"
        grievance_type: Optional subtype e.g. "Verbal", "Written" (can be empty)
    """
    # Backend uses @RequestPart — must send as multipart/form-data
    # employeeId goes in a REQUEST HEADER, not the body
    parts = {
        "category": (None, category),
        "subject":  (None, subject),
        "description": (None, description),
    }
    if grievance_type:
        parts["type"] = (None, grievance_type)

    headers = {
        "Authorization": f"Bearer {_current_token.get()}",
        "employeeId": _current_employee_id.get(),   # required as request header
    }

    url = f"{_base()}/api/grievances/anonymous"
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.post(url, files=parts, headers=headers)
        if resp.status_code in (200, 201):
            data = resp.json()
            gid = data.get("grievanceId") or data.get("id") or "N/A"
            return (
                f"✅ Grievance raised successfully!\n"
                f"Grievance ID : {gid}\n"
                f"Subject      : {subject}\n"
                f"Category     : {category}\n"
                f"Status       : Submitted (under review)"
            )
        return _fmt_error(resp, "Raise grievance")
    except httpx.ConnectError:
        return "❌ Cannot connect to Xevyte backend."
    except Exception as e:
        return f"❌ Unexpected error: {e}"


# ─── 7. Submit helpdesk ticket ────────────────────────────────────────────────
@tool
def submit_ticket(
    category: str,
    subcategory: str,
    issue_summary: str,
    detailed_description: str,
    cc_to_manager: bool = False,
) -> str:
    """
    Submit a helpdesk support ticket.

    Args:
        category:             Main category e.g. "IT", "HR", "Admin", "Finance", "Facilities"
        subcategory:          Sub-category e.g. "Laptop Issue", "Software Access",
                              "ID Card", "Salary Query", "Reimbursement"
        issue_summary:        One-line summary of the issue
        detailed_description: Complete description of the problem
        cc_to_manager:        Set True to copy the manager on this ticket
    """
    # @RequestParam with MultipartFile — Spring requires multipart/form-data
    # Use files= with (None, value) tuples for text fields
    parts = {
        "employeeId":          (None, _current_employee_id.get()),
        "category":            (None, category),
        "subcategory":         (None, subcategory),
        "issueSummary":        (None, issue_summary),
        "detailedDescription": (None, detailed_description),
        "ccToManager":         (None, "true" if cc_to_manager else "false"),
    }

    url = f"{_base()}/api/tickets/submit"
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.post(url, files=parts, headers=_auth_headers())
        if resp.status_code in (200, 201):
            data = resp.json()
            tid = data.get("id") or data.get("ticketId") or "N/A"
            return (
                f"✅ Ticket submitted successfully!\n"
                f"Ticket ID    : {tid}\n"
                f"Category     : {category} → {subcategory}\n"
                f"Summary      : {issue_summary}\n"
                f"CC Manager   : {'Yes' if cc_to_manager else 'No'}"
            )
        return _fmt_error(resp, "Submit ticket")
    except httpx.ConnectError:
        return "❌ Cannot connect to Xevyte backend."
    except Exception as e:
        return f"❌ Unexpected error: {e}"


# ─── 8. Get my tickets ────────────────────────────────────────────────────────
@tool
def get_my_tickets() -> str:
    """
    Retrieve all helpdesk tickets submitted by the logged-in employee
    with their current status.
    """
    url = f"{_base()}/api/tickets/my-tickets/{_current_employee_id.get()}"
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(url, headers=_auth_headers())
        if resp.status_code == 200:
            data = resp.json()
            if not data:
                return "You have no helpdesk tickets."
            return str(data[:15])
        return _fmt_error(resp, "Get tickets")
    except httpx.ConnectError:
        return "❌ Cannot connect to Xevyte backend."
    except Exception as e:
        return f"❌ Unexpected error: {e}"


# ─── 9. Get notifications ─────────────────────────────────────────────────────
@tool
def get_notifications() -> str:
    """
    Get all notifications for the logged-in employee (read and unread).
    """
    url = f"{_base()}/api/notifications/{_current_employee_id.get()}"
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(url, headers=_auth_headers())
        if resp.status_code == 200:
            data = resp.json()
            if not data:
                return "No notifications found."
            unread = [n for n in data if not n.get("read", False)]
            return (
                f"You have {len(unread)} unread notification(s) out of {len(data)} total.\n"
                + str(data[:10])
            )
        return _fmt_error(resp, "Get notifications")
    except httpx.ConnectError:
        return "❌ Cannot connect to Xevyte backend."
    except Exception as e:
        return f"❌ Unexpected error: {e}"


# ─── 10. Get attendance summary ───────────────────────────────────────────────
@tool
def get_attendance_summary(start_date: str, end_date: str) -> str:
    """
    Get attendance analytics for the logged-in employee over a date range.

    Args:
        start_date: Start date in YYYY-MM-DD format e.g. "2026-07-01"
        end_date:   End date in YYYY-MM-DD format e.g. "2026-07-31"
    """
    # This endpoint expects YYYY-MM-DD (ISO format)
    try:
        sd = datetime.strptime(_to_backend_date(start_date), "%d-%m-%Y").strftime("%Y-%m-%d")
        ed = datetime.strptime(_to_backend_date(end_date), "%d-%m-%Y").strftime("%Y-%m-%d")
    except Exception:
        sd, ed = start_date, end_date

    url = f"{_base()}/api/v1/analytics/me"
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(url, params={"startDate": sd, "endDate": ed}, headers=_auth_headers())
        if resp.status_code == 200:
            return str(resp.json())
        return _fmt_error(resp, "Get attendance")
    except httpx.ConnectError:
        return "❌ Cannot connect to Xevyte backend."
    except Exception as e:
        return f"❌ Unexpected error: {e}"


# ─── 10b. Check Today's Attendance ────────────────────────────────────────────
@tool
def check_today_attendance() -> str:
    """
    Check if the logged-in employee has already marked their attendance for today.
    Use this to verify attendance status before attempting to mark attendance.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    url = f"{_base()}/api/daily-entry/employee/{_current_employee_id.get()}"
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(url, headers=_auth_headers())
        if resp.status_code == 200:
            entries = resp.json()
            for entry in entries:
                if entry.get("date") == today:
                    return f"Attendance already marked for today ({today}). Status: {entry.get('status')}, Location: {entry.get('workLocation')}"
            return "Attendance NOT marked for today yet."
        return _fmt_error(resp, "Check today's attendance")
    except httpx.ConnectError:
        return "❌ Cannot connect to Xevyte backend."
    except Exception as e:
        return f"❌ Unexpected error: {e}"


# ─── 11. Get employee profile ─────────────────────────────────────────────────
@tool
def get_my_profile() -> str:
    """
    Retrieve the logged-in employee's full profile: department, designation,
    manager, contact info, joining date, and personal details.
    """
    url = f"{_base()}/api/employees/{_current_employee_id.get()}"
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(url, headers=_auth_headers())
        if resp.status_code == 200:
            return str(resp.json())
        return _fmt_error(resp, "Get profile")
    except httpx.ConnectError:
        return "❌ Cannot connect to Xevyte backend."
    except Exception as e:
        return f"❌ Unexpected error: {e}"


# ─── 12. Get task summary ─────────────────────────────────────────────────────
@tool
def get_task_summary() -> str:
    """
    Get a dashboard summary of pending tasks for the logged-in employee:
    pending leave approvals, open tickets, grievances, etc.
    """
    url = f"{_base()}/api/task-counts/{_current_employee_id.get()}"
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(url, headers=_auth_headers())
        if resp.status_code == 200:
            return str(resp.json())
        return _fmt_error(resp, "Get task summary")
    except httpx.ConnectError:
        return "❌ Cannot connect to Xevyte backend."
    except Exception as e:
        return f"❌ Unexpected error: {e}"


# ─── 13. Mark notification as read ───────────────────────────────────────────
@tool
def mark_notification_read(notification_id: int) -> str:
    """
    Mark a specific notification as read by its ID.

    Args:
        notification_id: Numeric ID of the notification to mark as read
    """
    url = f"{_base()}/api/notifications/read/{notification_id}"
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(url, headers=_auth_headers())
        if resp.status_code == 200:
            return f"✅ Notification #{notification_id} marked as read."
        return _fmt_error(resp, "Mark notification read")
    except httpx.ConnectError:
        return "❌ Cannot connect to Xevyte backend."
    except Exception as e:
        return f"❌ Unexpected error: {e}"


# ─── 14. Get holidays list ────────────────────────────────────────────────────
@tool
def get_holidays() -> str:
    """
    Get the list of company holidays for the current year.
    """
    url = f"{_base()}/api/leaves/holidays"
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(url, headers=_auth_headers())
        if resp.status_code == 200:
            data = resp.json()
            if not data:
                return "No holidays found."
            return str(data[:30])
        return _fmt_error(resp, "Get holidays")
    except httpx.ConnectError:
        return "❌ Cannot connect to Xevyte backend."
    except Exception as e:
        return f"❌ Unexpected error: {e}"


# ─── 15. Get approved leave dates ────────────────────────────────────────────
@tool
def get_approved_leave_dates() -> str:
    """
    Get all approved leave dates for the logged-in employee.
    Useful to check which dates are already blocked.
    """
    url = f"{_base()}/api/leaves/approved-dates/{_current_employee_id.get()}"
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(url, headers=_auth_headers())
        if resp.status_code == 200:
            data = resp.json()
            if not data:
                return "No approved leave dates found."
            return str(data)
        return _fmt_error(resp, "Get approved leave dates")
    except httpx.ConnectError:
        return "❌ Cannot connect to Xevyte backend."
    except Exception as e:
        return f"❌ Unexpected error: {e}"


# ─── 16. Mark attendance ───────────────────────────────────────────────────────
@tool
def mark_attendance(
    work_location: str,
    date: str = "",
    action: str = "check_in",
    client_name: str = "",
    project_name: str = "",
    remarks: str = "Marked via Xeva Agent",
) -> str:
    """
    Mark attendance, check-in, or check-out for the logged-in employee.

    Args:
        work_location: REQUIRED. Location e.g. "Office", "WFH", "Client Location". You must ask the user for this before calling the tool.
        date: Date in YYYY-MM-DD format (defaults to today if empty)
        action: Either "check_in", "check_out", or "mark_present"
        client_name: Optional client name if working on a client project
        project_name: Optional project name if working on a specific project
        remarks: Optional remarks or notes
    """
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    else:
        d_str = _to_backend_date(date)
        try:
            date = datetime.strptime(d_str, "%d-%m-%Y").strftime("%Y-%m-%d")
        except Exception:
            pass

    now_time = datetime.now().strftime("%H:%M")
    
    payload = {
        "date": date,
        "workLocation": work_location,
        "loginWorkLocation": work_location,
        "remarks": remarks,
        "status": "PRESENT"
    }

    if client_name:
        payload["clientName"] = client_name
    if project_name:
        payload["projectName"] = project_name

    if action in ("check_in", "mark_present"):
        payload["loginTime"] = now_time
    elif action == "check_out":
        payload["logoutTime"] = now_time

    url = f"{_base()}/api/daily-entry/submit/{_current_employee_id.get()}"
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(url, json=payload, headers=_auth_headers())
        if resp.status_code in (200, 201):
            action_desc = "Check-in" if action == "check_in" else ("Check-out" if action == "check_out" else "Attendance")
            return (
                f"✅ {action_desc} marked successfully for {_current_employee_id.get()}!\n"
                f"Date          : {date}\n"
                f"Time          : {now_time}\n"
                f"Work Location : {work_location}\n"
                f"Status        : Present"
            )
        return _fmt_error(resp, "Mark attendance")
    except httpx.ConnectError:
        return "❌ Cannot connect to Xevyte backend."
    except Exception as e:
        return f"❌ Unexpected error: {e}"



# ─── 5. Approve/Reject Leave (Manager/Admin) ──────────────────────────────────
@tool
def action_leave(leave_id_or_ref: str, action: str, role: str = "Manager", remarks: str = "") -> str:
    """
    Approve or Reject a leave request. (For Managers, HR, or Admins).
    You can provide either the numeric ID or the string Reference ID (e.g., 'SCA-LV-2026-000045').

    Args:
        leave_id_or_ref: Numeric ID or Reference ID of the leave request.
        action: "Approve" or "Reject"
        role: Your role, e.g. "Manager" or "HR". Defaults to "Manager".
        remarks: Optional comments explaining the decision.
    """
    leave_id = str(leave_id_or_ref).strip()
    
    # If the provided ID is not strictly numeric, we must look up the numeric ID
    if not leave_id.isdigit():
        manager_url = f"{_base()}/api/leaves/manager/{_current_employee_id.get()}"
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.get(manager_url, headers=_auth_headers())
            if resp.status_code == 200:
                manager_data = resp.json()
                found_id = None
                for req in manager_data:
                    if req.get("referenceId") == leave_id or str(req.get("id")) == leave_id:
                        found_id = req.get("id")
                        break
                if not found_id:
                    return f"❌ Could not find a leave request matching reference '{leave_id}' for your approval."
                leave_id = str(found_id)
            else:
                return f"❌ Could not look up leave reference '{leave_id}' (HTTP {resp.status_code})."
        except Exception as e:
            return f"❌ Error looking up leave reference: {e}"

    url = f"{_base()}/api/leaves/action"
    payload = {
        "leaveRequestId": int(leave_id),
        "approverId": _current_employee_id.get(),
        "role": role,
        "action": action,
        "remarks": remarks
    }
    
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(url, json=payload, headers=_json_headers())
        if resp.status_code in (200, 201):
            data = resp.json()
            return (
                f"✅ Leave {leave_id_or_ref} {action}d successfully.\n"
                f"Status: {data.get('status', 'Unknown')}"
            )
        return _fmt_error(resp, f"{action} leave {leave_id_or_ref}")
    except httpx.ConnectError:
        return "❌ Cannot connect to Xevyte backend."
    except Exception as e:
        return f"❌ Unexpected error: {e}"


@tool
def get_pending_approvals() -> str:
    """
    Get the list of leave requests waiting for your approval as a Manager.
    Use this to find reference IDs or numeric IDs for leaves you need to approve.
    """
    url = f"{_base()}/api/leaves/manager/{_current_employee_id.get()}"
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(url, headers=_auth_headers())
        if resp.status_code == 200:
            data = resp.json()
            if not data:
                return "No pending leave requests for your approval."
            
            # Match backend task-counts logic: starts with pending or is sent back
            pending = []
            for req in data:
                status = req.get("status", "").upper()
                if status.startswith("PENDING") or status == "SENT BACK FOR REVISION":
                    pending.append(req)
                    
            if not pending:
                return "You have no PENDING leave requests for approval."
            return str(pending[:15])
        return _fmt_error(resp, "Get pending approvals")
    except httpx.ConnectError:
        return "❌ Cannot connect to Xevyte backend."
    except Exception as e:
        return f"❌ Unexpected error: {e}"


# ─── Tool registry ────────────────────────────────────────────────────────────
ALL_TOOLS = [
    get_leave_balance,
    get_leave_history,
    apply_leave,
    cancel_leave,
    action_leave,
    get_pending_approvals,
    raise_grievance,
    submit_ticket,
    get_my_tickets,
    get_notifications,
    mark_notification_read,
    get_attendance_summary,
    check_today_attendance,
    get_my_profile,
    get_task_summary,
    get_holidays,
    get_approved_leave_dates,
    mark_attendance,
]
