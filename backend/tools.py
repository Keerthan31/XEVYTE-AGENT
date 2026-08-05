"""
HRMS Tool functions — each one calls a Xevyte Connect REST API endpoint.
All tools receive the JWT token (from Scaloz IAM) via a shared context
that is injected by the agent before each tool call.

Includes enterprise-grade features:
- Structured JSON outputs (success, message, data, metadata)
- Automatic HTTP retries with exponential backoff
- In-memory TTL caching for read-only tools
- Parameter validation & sanitization
"""

import json
import time
import httpx
import logging
import threading
from contextvars import ContextVar
from datetime import datetime, date, timedelta
from langchain_core.tools import tool
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, retry_if_result
from config import XEVYTE_API_BASE, CACHE_TTL_SECONDS, MAX_HTTP_RETRIES, HTTP_TIMEOUT_SECONDS

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


# ─── Pydantic v2 Input Validation Schemas ─────────────────────────────────────
from pydantic import BaseModel, Field


class ApplyLeaveInput(BaseModel):
    leave_type: str = Field(..., description="Leave type e.g. EL, SL, CL, Optional")
    start_date: str = Field(..., description="Start date e.g. 27-07-2026 or today")
    end_date: str = Field(..., description="End date e.g. 29-07-2026")
    reason: str = Field(..., description="Reason for applying leave")
    half_day: bool = Field(default=False, description="True for half day leave")


class MarkAttendanceInput(BaseModel):
    work_location: str = Field(..., description="Work location e.g. Office, WFH, Client Location")
    date: str = Field(default="", description="Date in YYYY-MM-DD format")
    action: str = Field(default="check_in", description="check_in, check_out, or mark_present")
    client_name: str = Field(default="", description="Optional client name")
    project_name: str = Field(default="", description="Optional project name")
    remarks: str = Field(default="", description="Remarks")


class SubmitTicketInput(BaseModel):
    category: str = Field(..., description="Category e.g. IT, HR, Admin")
    subcategory: str = Field(..., description="Subcategory e.g. Laptop Issue, ID Card")
    issue_summary: str = Field(..., description="One-line summary")
    detailed_description: str = Field(..., description="Detailed issue description")
    cc_to_manager: bool = Field(default=False, description="Copy manager")


class ActionLeaveInput(BaseModel):
    leave_id_or_ref: str = Field(..., description="Numeric ID or Reference ID")
    action: str = Field(..., description="Approve or Reject")
    role: str = Field(default="Manager", description="Manager or HR")
    remarks: str = Field(default="", description="Optional remarks")


class UpdatePersonalDetailsInput(BaseModel):
    phone_number: str = Field(..., pattern=r"^\d{10}$", description="Must be exactly 10 digits")
    emergency_contact: str = Field(..., pattern=r"^\d{10}$", description="Must be exactly 10 digits")
    current_address: str = Field(..., min_length=5, description="Current Address")
    permanent_address: str = Field(..., min_length=5, description="Permanent Address")
    personal_mail: str = Field(default="", pattern=r"^[\w\.-]+@[\w\.-]+\.\w+$", description="Valid email format")


class UpdateBankDetailsInput(BaseModel):
    bank_name: str = Field(..., min_length=2, description="Name of the bank")
    account_number: str = Field(..., pattern=r"^\d{9,18}$", description="Bank account number (9-18 digits)")
    ifsc_code: str = Field(..., pattern=r"^[A-Z]{4}0[A-Z0-9]{6}$", description="Valid Indian Bank IFSC code")
    uan_number: str = Field(default="", pattern=r"^(?:\d{12})?$", description="UAN Number (exactly 12 digits if provided)")
    pf_member_id: str = Field(default="", description="PF Member ID")
    esi_number: str = Field(default="", pattern=r"^(?:\d{17})?$", description="ESI Number (exactly 17 digits if provided)")
    esi_dispensary: str = Field(default="", description="ESI Dispensary / Clinic Name")


class AddNomineeInput(BaseModel):
    nominee_name: str = Field(..., description="Full name of the nominee")
    relationship: str = Field(..., description="Relationship to the employee (e.g. Spouse, Father, Mother)")
    date_of_birth: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Date of birth in YYYY-MM-DD format")


# ─── Structured Response Envelope ─────────────────────────────────────────────
def format_tool_response(
    success: bool,
    message: str,
    data: dict | list | None = None,
    tool_name: str = "",
    exec_time_ms: float = 0.0,
    cached: bool = False,
    error_code: str | None = None,
) -> str:
    """Standardized JSON response envelope across all tools."""
    res = {
        "success": success,
        "message": message,
        "data": data if data is not None else {},
        "metadata": {
            "tool": tool_name,
            "timestamp": datetime.now().isoformat(),
            "execution_time_ms": round(exec_time_ms, 2),
            "cached": cached,
        }
    }
    if error_code:
        res["metadata"]["error_code"] = error_code
    return json.dumps(res, indent=2, default=str)


# ─── In-Memory TTL Cache Layer ─────────────────────────────────────────────────
class _TTLCache:
    """Thread-safe TTL Cache for read-only tools."""

    def __init__(self, ttl_seconds: int = CACHE_TTL_SECONDS):
        self.ttl = ttl_seconds
        self._store: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            if key in self._store:
                timestamp, val = self._store[key]
                if time.time() - timestamp <= self.ttl:
                    return val
                del self._store[key]
        return None

    def set(self, key: str, val: str):
        with self._lock:
            self._store[key] = (time.time(), val)

    def invalidate(self, prefix: str = ""):
        with self._lock:
            if not prefix:
                self._store.clear()
            else:
                keys = [k for k in self._store if k.startswith(prefix)]
                for k in keys:
                    del self._store[k]


_cache = _TTLCache(ttl_seconds=CACHE_TTL_SECONDS)


# ─── HTTP Connection & Retry Wrapper ──────────────────────────────────────────
def _is_server_error(resp: httpx.Response | BaseException) -> bool:
    if isinstance(resp, httpx.Response):
        return resp.status_code >= 500
    return False

@retry(
    stop=stop_after_attempt(MAX_HTTP_RETRIES),
    wait=wait_exponential(multiplier=0.5, min=1, max=10),
    retry=(
        retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError)) |
        retry_if_result(_is_server_error)
    ),
    reraise=True,
)
def _httpx_request_tenacity(
    method: str,
    url: str,
    headers: dict | None = None,
    params: dict | None = None,
    json_data: dict | None = None,
    files: dict | None = None,
    timeout: float = HTTP_TIMEOUT_SECONDS,
) -> httpx.Response:
    """Execute HTTP request with Tenacity exponential backoff for 5xx/network errors."""
    with httpx.Client(timeout=timeout) as client:
        resp = client.request(
            method, url, headers=headers, params=params, json=json_data, files=files
        )
        return resp

def _httpx_request(
    method: str,
    url: str,
    headers: dict | None = None,
    params: dict | None = None,
    json_data: dict | None = None,
    files: dict | None = None,
    timeout: float = HTTP_TIMEOUT_SECONDS,
) -> httpx.Response:
    try:
        return _httpx_request_tenacity(method, url, headers, params, json_data, files, timeout)
    except Exception as e:
        logger.warning(f"HTTP request failed after retries: {e}")
        raise e


# ─── Date & Validation Helpers ────────────────────────────────────────────────
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
    """Accept any common date format from LLM and return dd-MM-yyyy."""
    date_str = date_str.strip().lower()

    if date_str == "today":
        return datetime.now().strftime("%d-%m-%Y")
    if date_str == "tomorrow":
        return (datetime.now() + timedelta(days=1)).strftime("%d-%m-%Y")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(date_str, fmt).strftime("%d-%m-%Y")
        except ValueError:
            continue
    logger.warning(f"Could not parse date: {date_str}")
    return date_str


def _validate_date(date_str: str) -> tuple[bool, str]:
    if not date_str or not date_str.strip():
        return False, "Date string cannot be empty."
    parsed = _to_backend_date(date_str)
    try:
        datetime.strptime(parsed, "%d-%m-%Y")
        return True, parsed
    except ValueError:
        return False, f"Invalid date format '{date_str}'."


def _validate_leave_type(leave_type: str) -> str:
    l_type_lower = leave_type.strip().lower()
    if "optional" in l_type_lower:
        return "Optional"
    elif "sick" in l_type_lower or l_type_lower == "sl":
        return "SL"
    elif "earned" in l_type_lower or l_type_lower == "el":
        return "EL"
    elif "casual" in l_type_lower or l_type_lower == "cl":
        return "CL"
    elif "lop" in l_type_lower or "loss" in l_type_lower:
        return "LOP"
    return leave_type.strip()


def _fmt_error(resp: httpx.Response, action: str, tool_name: str, exec_time_ms: float) -> str:
    """Return formatted structured error json."""
    try:
        body = resp.json()
        msg = body.get("message") or body.get("error") or body.get("detail") or str(body)
    except Exception:
        msg = resp.text[:400] or "(no body)"

    return format_tool_response(
        success=False,
        message=f"{action} failed (HTTP {resp.status_code}): {msg}",
        data={"http_status": resp.status_code, "raw_response": msg},
        tool_name=tool_name,
        exec_time_ms=exec_time_ms,
        error_code=f"HTTP_{resp.status_code}",
    )


# ─── 1. Get leave balance (detailed) ─────────────────────────────────────────
@tool
def get_leave_balance() -> str:
    """
    Fetch the current leave balance for the logged-in employee.
    Returns each leave type with granted, consumed, and remaining days.
    """
    t0 = time.time()
    emp_id = _current_employee_id.get()
    cache_key = f"get_leave_balance:{emp_id}"
    cached_val = _cache.get(cache_key)
    if cached_val:
        return cached_val

    url = f"{_base()}/api/leaves/balance/details/{emp_id}"
    try:
        resp = _httpx_request("GET", url, headers=_auth_headers())
        exec_time = (time.time() - t0) * 1000
        if resp.status_code == 200:
            data = resp.json()
            res_json = format_tool_response(
                success=True,
                message=f"Leave balance retrieved for employee {emp_id}.",
                data=data if data else [],
                tool_name="get_leave_balance",
                exec_time_ms=exec_time,
            )
            _cache.set(cache_key, res_json)
            return res_json
        return _fmt_error(resp, "Get leave balance", "get_leave_balance", exec_time)
    except httpx.ConnectError:
        return format_tool_response(
            success=False,
            message="Cannot connect to Xevyte backend. Please ensure the backend service is running.",
            tool_name="get_leave_balance",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="CONNECT_ERROR",
        )
    except Exception as e:
        return format_tool_response(
            success=False,
            message=f"Unexpected error: {str(e)}",
            tool_name="get_leave_balance",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="INTERNAL_ERROR",
        )


# ─── 2. Get leave history ─────────────────────────────────────────────────────
@tool
def get_leave_history() -> str:
    """
    Get the full leave request history for the logged-in employee,
    including status (Pending, Approved, Rejected, Cancelled).
    """
    t0 = time.time()
    emp_id = _current_employee_id.get()
    url = f"{_base()}/api/leaves/employee/{emp_id}"
    try:
        resp = _httpx_request("GET", url, headers=_auth_headers())
        exec_time = (time.time() - t0) * 1000
        if resp.status_code == 200:
            data = resp.json()
            return format_tool_response(
                success=True,
                message=f"Leave history retrieved ({len(data)} records found).",
                data=data[::-1][:20] if data else [],
                tool_name="get_leave_history",
                exec_time_ms=exec_time,
            )
        return _fmt_error(resp, "Get leave history", "get_leave_history", exec_time)
    except httpx.ConnectError:
        return format_tool_response(
            success=False,
            message="Cannot connect to Xevyte backend.",
            tool_name="get_leave_history",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="CONNECT_ERROR",
        )
    except Exception as e:
        return format_tool_response(
            success=False,
            message=f"Unexpected error: {str(e)}",
            tool_name="get_leave_history",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="INTERNAL_ERROR",
        )


# ─── 3. Apply for leave ───────────────────────────────────────────────────────
@tool(args_schema=ApplyLeaveInput)
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
        leave_type: Leave type (e.g., "EL", "SL", "Optional", "CL").
        start_date: Start date e.g. "27-07-2026" or "2026-07-27"
        end_date:   End date e.g. "29-07-2026"
        reason:     Reason for leave
        half_day:   True only for half-day leave
    """
    t0 = time.time()
    valid_sd, sd_str = _validate_date(start_date)
    if not valid_sd:
        return format_tool_response(
            success=False,
            message=f"Invalid start date: {sd_str}",
            tool_name="apply_leave",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="VALIDATION_ERROR",
        )

    valid_ed, ed_str = _validate_date(end_date)
    if not valid_ed:
        return format_tool_response(
            success=False,
            message=f"Invalid end date: {ed_str}",
            tool_name="apply_leave",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="VALIDATION_ERROR",
        )

    try:
        sd = datetime.strptime(sd_str, "%d-%m-%Y").date()
        ed = datetime.strptime(ed_str, "%d-%m-%Y").date()
        if ed < sd:
            return format_tool_response(
                success=False,
                message="End date cannot be before start date.",
                tool_name="apply_leave",
                exec_time_ms=(time.time() - t0) * 1000,
                error_code="VALIDATION_ERROR",
            )
    except Exception as e:
        return format_tool_response(
            success=False,
            message=f"Date parsing error: {e}",
            tool_name="apply_leave",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="VALIDATION_ERROR",
        )

    norm_leave_type = _validate_leave_type(leave_type)
    emp_id = _current_employee_id.get()

    payload = {
        "employeeId": emp_id,
        "type": norm_leave_type,
        "startDate": sd_str,
        "endDate": ed_str,
        "reason": reason,
        "halfDay": half_day,
    }

    url = f"{_base()}/api/leaves/apply"
    files = {"dto": (None, json.dumps(payload), "application/json")}

    try:
        resp = _httpx_request("POST", url, files=files, headers=_auth_headers(), timeout=20.0)
        exec_time = (time.time() - t0) * 1000
        if resp.status_code in (200, 201):
            data = resp.json()
            _cache.invalidate(prefix=f"get_leave_balance:{emp_id}")
            return format_tool_response(
                success=True,
                message="Leave application submitted successfully.",
                data=data,
                tool_name="apply_leave",
                exec_time_ms=exec_time,
            )
        return _fmt_error(resp, "Apply leave", "apply_leave", exec_time)
    except httpx.ConnectError:
        return format_tool_response(
            success=False,
            message="Cannot connect to Xevyte backend.",
            tool_name="apply_leave",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="CONNECT_ERROR",
        )
    except Exception as e:
        return format_tool_response(
            success=False,
            message=f"Unexpected error: {str(e)}",
            tool_name="apply_leave",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="INTERNAL_ERROR",
        )


# ─── 4. Cancel leave ──────────────────────────────────────────────────────────
@tool
def cancel_leave(leave_id_or_ref: str) -> str:
    """
    Cancel a pending leave request by numeric ID or Reference ID (e.g., 'SCA-LV-2026-000043').
    """
    t0 = time.time()
    leave_id = str(leave_id_or_ref).strip()
    emp_id = _current_employee_id.get()

    if not leave_id.isdigit():
        history_url = f"{_base()}/api/leaves/employee/{emp_id}"
        try:
            resp = _httpx_request("GET", history_url, headers=_auth_headers())
            if resp.status_code == 200:
                history_data = resp.json()
                found_id = None
                for req in history_data:
                    if req.get("referenceId") == leave_id or str(req.get("id")) == leave_id:
                        found_id = req.get("id")
                        break
                if not found_id:
                    return format_tool_response(
                        success=False,
                        message=f"Could not find a leave request matching reference '{leave_id}'.",
                        tool_name="cancel_leave",
                        exec_time_ms=(time.time() - t0) * 1000,
                        error_code="NOT_FOUND",
                    )
                leave_id = str(found_id)
            else:
                return _fmt_error(resp, "Lookup leave reference", "cancel_leave", (time.time() - t0) * 1000)
        except Exception as e:
            return format_tool_response(
                success=False,
                message=f"Error looking up leave reference: {e}",
                tool_name="cancel_leave",
                exec_time_ms=(time.time() - t0) * 1000,
                error_code="LOOKUP_ERROR",
            )

    url = f"{_base()}/api/leaves/cancel/{leave_id}"
    try:
        resp = _httpx_request("PUT", url, headers=_auth_headers())
        exec_time = (time.time() - t0) * 1000
        if resp.status_code in (200, 204):
            _cache.invalidate(prefix=f"get_leave_balance:{emp_id}")
            return format_tool_response(
                success=True,
                message=f"Leave request #{leave_id_or_ref} cancelled successfully.",
                data={"leave_id": leave_id, "reference_id": leave_id_or_ref},
                tool_name="cancel_leave",
                exec_time_ms=exec_time,
            )
        return _fmt_error(resp, f"Cancel leave {leave_id_or_ref}", "cancel_leave", exec_time)
    except httpx.ConnectError:
        return format_tool_response(
            success=False,
            message="Cannot connect to Xevyte backend.",
            tool_name="cancel_leave",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="CONNECT_ERROR",
        )
    except Exception as e:
        return format_tool_response(
            success=False,
            message=f"Unexpected error: {str(e)}",
            tool_name="cancel_leave",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="INTERNAL_ERROR",
        )


# ─── 5. Approve/Reject Leave (Manager/Admin) ──────────────────────────────────
@tool(args_schema=ActionLeaveInput)
def action_leave(leave_id_or_ref: str, action: str, role: str = "Manager", remarks: str = "") -> str:
    """
    Approve or Reject a leave request. (For Managers, HR, or Admins).
    """
    t0 = time.time()
    leave_id = str(leave_id_or_ref).strip()
    emp_id = _current_employee_id.get()

    if not leave_id.isdigit():
        manager_url = f"{_base()}/api/leaves/manager/{emp_id}"
        try:
            resp = _httpx_request("GET", manager_url, headers=_auth_headers())
            if resp.status_code == 200:
                manager_data = resp.json()
                found_id = None
                for req in manager_data:
                    if req.get("referenceId") == leave_id or str(req.get("id")) == leave_id:
                        found_id = req.get("id")
                        break
                if not found_id:
                    return format_tool_response(
                        success=False,
                        message=f"Could not find leave request matching reference '{leave_id}' for your approval.",
                        tool_name="action_leave",
                        exec_time_ms=(time.time() - t0) * 1000,
                        error_code="NOT_FOUND",
                    )
                leave_id = str(found_id)
            else:
                return _fmt_error(resp, "Lookup leave reference", "action_leave", (time.time() - t0) * 1000)
        except Exception as e:
            return format_tool_response(
                success=False,
                message=f"Error looking up leave reference: {e}",
                tool_name="action_leave",
                exec_time_ms=(time.time() - t0) * 1000,
                error_code="LOOKUP_ERROR",
            )

    url = f"{_base()}/api/leaves/action"
    payload = {
        "leaveRequestId": int(leave_id),
        "approverId": emp_id,
        "role": role,
        "action": action,
        "remarks": remarks
    }

    try:
        resp = _httpx_request("POST", url, json_data=payload, headers=_json_headers())
        exec_time = (time.time() - t0) * 1000
        if resp.status_code in (200, 201):
            data = resp.json()
            return format_tool_response(
                success=True,
                message=f"Leave request #{leave_id_or_ref} {action}d successfully.",
                data=data,
                tool_name="action_leave",
                exec_time_ms=exec_time,
            )
        return _fmt_error(resp, f"{action} leave {leave_id_or_ref}", "action_leave", exec_time)
    except httpx.ConnectError:
        return format_tool_response(
            success=False,
            message="Cannot connect to Xevyte backend.",
            tool_name="action_leave",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="CONNECT_ERROR",
        )
    except Exception as e:
        return format_tool_response(
            success=False,
            message=f"Unexpected error: {str(e)}",
            tool_name="action_leave",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="INTERNAL_ERROR",
        )


@tool
def get_pending_approvals() -> str:
    """
    Get the list of leave requests waiting for your approval as a Manager.
    """
    t0 = time.time()
    emp_id = _current_employee_id.get()
    url = f"{_base()}/api/leaves/manager/{emp_id}"
    try:
        resp = _httpx_request("GET", url, headers=_auth_headers())
        exec_time = (time.time() - t0) * 1000
        if resp.status_code == 200:
            data = resp.json()
            pending = []
            if data:
                for req in data:
                    status = req.get("status", "").upper()
                    if status.startswith("PENDING") or status == "SENT BACK FOR REVISION":
                        pending.append(req)
            return format_tool_response(
                success=True,
                message=f"Retrieved {len(pending)} pending leave requests for approval.",
                data=pending[::-1][:15],
                tool_name="get_pending_approvals",
                exec_time_ms=exec_time,
            )
        return _fmt_error(resp, "Get pending approvals", "get_pending_approvals", exec_time)
    except httpx.ConnectError:
        return format_tool_response(
            success=False,
            message="Cannot connect to Xevyte backend.",
            tool_name="get_pending_approvals",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="CONNECT_ERROR",
        )
    except Exception as e:
        return format_tool_response(
            success=False,
            message=f"Unexpected error: {str(e)}",
            tool_name="get_pending_approvals",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="INTERNAL_ERROR",
        )


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
    """
    t0 = time.time()
    if not subject or not subject.strip():
        return format_tool_response(
            success=False,
            message="Grievance subject cannot be empty.",
            tool_name="raise_grievance",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="VALIDATION_ERROR",
        )

    parts = {
        "category": (None, category),
        "subject": (None, subject),
        "description": (None, description),
    }
    if grievance_type:
        parts["type"] = (None, grievance_type)

    headers = {
        "Authorization": f"Bearer {_current_token.get()}",
        "employeeId": _current_employee_id.get(),
    }

    url = f"{_base()}/api/grievances/anonymous"
    try:
        resp = _httpx_request("POST", url, files=parts, headers=headers, timeout=20.0)
        exec_time = (time.time() - t0) * 1000
        if resp.status_code in (200, 201):
            data = resp.json()
            return format_tool_response(
                success=True,
                message="Grievance raised successfully.",
                data=data,
                tool_name="raise_grievance",
                exec_time_ms=exec_time,
            )
        return _fmt_error(resp, "Raise grievance", "raise_grievance", exec_time)
    except httpx.ConnectError:
        return format_tool_response(
            success=False,
            message="Cannot connect to Xevyte backend.",
            tool_name="raise_grievance",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="CONNECT_ERROR",
        )
    except Exception as e:
        return format_tool_response(
            success=False,
            message=f"Unexpected error: {str(e)}",
            tool_name="raise_grievance",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="INTERNAL_ERROR",
        )


# ─── 7. Submit helpdesk ticket ────────────────────────────────────────────────
@tool(args_schema=SubmitTicketInput)
def submit_ticket(
    category: str,
    subcategory: str,
    issue_summary: str,
    detailed_description: str,
    cc_to_manager: bool = False,
) -> str:
    """
    Submit a helpdesk support ticket.
    """
    t0 = time.time()
    if not issue_summary or not issue_summary.strip():
        return format_tool_response(
            success=False,
            message="Ticket issue summary cannot be empty.",
            tool_name="submit_ticket",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="VALIDATION_ERROR",
        )

    parts = {
        "employeeId": (None, _current_employee_id.get()),
        "category": (None, category),
        "subcategory": (None, subcategory),
        "issueSummary": (None, issue_summary),
        "detailedDescription": (None, detailed_description),
        "ccToManager": (None, "true" if cc_to_manager else "false"),
    }

    url = f"{_base()}/api/tickets/submit"
    try:
        resp = _httpx_request("POST", url, files=parts, headers=_auth_headers(), timeout=20.0)
        exec_time = (time.time() - t0) * 1000
        if resp.status_code in (200, 201):
            data = resp.json()
            return format_tool_response(
                success=True,
                message="Support ticket submitted successfully.",
                data=data,
                tool_name="submit_ticket",
                exec_time_ms=exec_time,
            )
        return _fmt_error(resp, "Submit ticket", "submit_ticket", exec_time)
    except httpx.ConnectError:
        return format_tool_response(
            success=False,
            message="Cannot connect to Xevyte backend.",
            tool_name="submit_ticket",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="CONNECT_ERROR",
        )
    except Exception as e:
        return format_tool_response(
            success=False,
            message=f"Unexpected error: {str(e)}",
            tool_name="submit_ticket",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="INTERNAL_ERROR",
        )


# ─── 8. Get my tickets ────────────────────────────────────────────────────────
@tool
def get_my_tickets() -> str:
    """
    Retrieve all helpdesk tickets submitted by the logged-in employee.
    """
    t0 = time.time()
    emp_id = _current_employee_id.get()
    url = f"{_base()}/api/tickets/my-tickets/{emp_id}"
    try:
        resp = _httpx_request("GET", url, headers=_auth_headers())
        exec_time = (time.time() - t0) * 1000
        if resp.status_code == 200:
            data = resp.json()
            return format_tool_response(
                success=True,
                message=f"Retrieved {len(data) if data else 0} tickets.",
                data=data[::-1][:15] if data else [],
                tool_name="get_my_tickets",
                exec_time_ms=exec_time,
            )
        return _fmt_error(resp, "Get tickets", "get_my_tickets", exec_time)
    except httpx.ConnectError:
        return format_tool_response(
            success=False,
            message="Cannot connect to Xevyte backend.",
            tool_name="get_my_tickets",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="CONNECT_ERROR",
        )
    except Exception as e:
        return format_tool_response(
            success=False,
            message=f"Unexpected error: {str(e)}",
            tool_name="get_my_tickets",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="INTERNAL_ERROR",
        )


# ─── 9. Get notifications ─────────────────────────────────────────────────────
@tool
def get_notifications() -> str:
    """
    Get all notifications for the logged-in employee (read and unread).
    """
    t0 = time.time()
    emp_id = _current_employee_id.get()
    url = f"{_base()}/api/notifications/{emp_id}"
    try:
        resp = _httpx_request("GET", url, headers=_auth_headers())
        exec_time = (time.time() - t0) * 1000
        if resp.status_code == 200:
            data = resp.json()
            unread_count = len([n for n in data if not n.get("read", False)]) if data else 0
            return format_tool_response(
                success=True,
                message=f"Retrieved {len(data) if data else 0} notifications ({unread_count} unread).",
                data=data[::-1][:15] if data else [],
                tool_name="get_notifications",
                exec_time_ms=exec_time,
            )
        return _fmt_error(resp, "Get notifications", "get_notifications", exec_time)
    except httpx.ConnectError:
        return format_tool_response(
            success=False,
            message="Cannot connect to Xevyte backend.",
            tool_name="get_notifications",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="CONNECT_ERROR",
        )
    except Exception as e:
        return format_tool_response(
            success=False,
            message=f"Unexpected error: {str(e)}",
            tool_name="get_notifications",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="INTERNAL_ERROR",
        )


# ─── 10. Get attendance summary ───────────────────────────────────────────────
@tool
def get_attendance_summary(start_date: str, end_date: str) -> str:
    """
    Get attendance analytics for the logged-in employee over a date range.
    """
    t0 = time.time()
    try:
        sd = datetime.strptime(_to_backend_date(start_date), "%d-%m-%Y").strftime("%Y-%m-%d")
        ed = datetime.strptime(_to_backend_date(end_date), "%d-%m-%Y").strftime("%Y-%m-%d")
    except Exception:
        sd, ed = start_date, end_date

    url = f"{_base()}/api/v1/analytics/me"
    try:
        resp = _httpx_request("GET", url, params={"startDate": sd, "endDate": ed}, headers=_auth_headers())
        exec_time = (time.time() - t0) * 1000
        if resp.status_code == 200:
            return format_tool_response(
                success=True,
                message=f"Attendance summary retrieved for range {sd} to {ed}.",
                data=resp.json(),
                tool_name="get_attendance_summary",
                exec_time_ms=exec_time,
            )
        return _fmt_error(resp, "Get attendance", "get_attendance_summary", exec_time)
    except httpx.ConnectError:
        return format_tool_response(
            success=False,
            message="Cannot connect to Xevyte backend.",
            tool_name="get_attendance_summary",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="CONNECT_ERROR",
        )
    except Exception as e:
        return format_tool_response(
            success=False,
            message=f"Unexpected error: {str(e)}",
            tool_name="get_attendance_summary",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="INTERNAL_ERROR",
        )


# ─── 10b. Check Today's Attendance ────────────────────────────────────────────
@tool
def check_today_attendance() -> str:
    """
    Check if the logged-in employee has already marked their attendance for today.
    """
    t0 = time.time()
    today = datetime.now().strftime("%Y-%m-%d")
    emp_id = _current_employee_id.get()
    url = f"{_base()}/api/daily-entry/employee/{emp_id}"
    try:
        resp = _httpx_request("GET", url, headers=_auth_headers())
        exec_time = (time.time() - t0) * 1000
        if resp.status_code == 200:
            entries = resp.json()
            for entry in entries:
                if entry.get("date") == today:
                    return format_tool_response(
                        success=True,
                        message=f"Attendance already marked for today ({today}).",
                        data={"marked": True, "entry": entry},
                        tool_name="check_today_attendance",
                        exec_time_ms=exec_time,
                    )
            return format_tool_response(
                success=True,
                message="Attendance NOT marked for today yet.",
                data={"marked": False},
                tool_name="check_today_attendance",
                exec_time_ms=exec_time,
            )
        return _fmt_error(resp, "Check today's attendance", "check_today_attendance", exec_time)
    except httpx.ConnectError:
        return format_tool_response(
            success=False,
            message="Cannot connect to Xevyte backend.",
            tool_name="check_today_attendance",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="CONNECT_ERROR",
        )
    except Exception as e:
        return format_tool_response(
            success=False,
            message=f"Unexpected error: {str(e)}",
            tool_name="check_today_attendance",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="INTERNAL_ERROR",
        )


# ─── 11. Get employee profile ─────────────────────────────────────────────────
@tool
def get_my_profile() -> str:
    """
    Retrieve the logged-in employee's full profile details.
    """
    t0 = time.time()
    emp_id = _current_employee_id.get()
    cache_key = f"get_my_profile:{emp_id}"
    cached_val = _cache.get(cache_key)
    if cached_val:
        return cached_val

    url = f"{_base()}/api/employees/{emp_id}"
    try:
        resp = _httpx_request("GET", url, headers=_auth_headers())
        exec_time = (time.time() - t0) * 1000
        if resp.status_code == 200:
            data = resp.json()
            res_json = format_tool_response(
                success=True,
                message=f"Profile retrieved for employee {emp_id}.",
                data=data,
                tool_name="get_my_profile",
                exec_time_ms=exec_time,
            )
            _cache.set(cache_key, res_json)
            return res_json
        return _fmt_error(resp, "Get profile", "get_my_profile", exec_time)
    except httpx.ConnectError:
        return format_tool_response(
            success=False,
            message="Cannot connect to Xevyte backend.",
            tool_name="get_my_profile",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="CONNECT_ERROR",
        )
    except Exception as e:
        return format_tool_response(
            success=False,
            message=f"Unexpected error: {str(e)}",
            tool_name="get_my_profile",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="INTERNAL_ERROR",
        )


# ─── 12. Get task summary ─────────────────────────────────────────────────────
@tool
def get_task_summary() -> str:
    """
    Get a dashboard summary of pending tasks for the logged-in employee.
    """
    t0 = time.time()
    emp_id = _current_employee_id.get()
    url = f"{_base()}/api/task-counts/{emp_id}"
    try:
        resp = _httpx_request("GET", url, headers=_auth_headers())
        exec_time = (time.time() - t0) * 1000
        if resp.status_code == 200:
            return format_tool_response(
                success=True,
                message=f"Task summary retrieved for employee {emp_id}.",
                data=resp.json(),
                tool_name="get_task_summary",
                exec_time_ms=exec_time,
            )
        return _fmt_error(resp, "Get task summary", "get_task_summary", exec_time)
    except httpx.ConnectError:
        return format_tool_response(
            success=False,
            message="Cannot connect to Xevyte backend.",
            tool_name="get_task_summary",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="CONNECT_ERROR",
        )
    except Exception as e:
        return format_tool_response(
            success=False,
            message=f"Unexpected error: {str(e)}",
            tool_name="get_task_summary",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="INTERNAL_ERROR",
        )


# ─── 13. Mark notification as read ───────────────────────────────────────────
@tool
def mark_notification_read(notification_id: int) -> str:
    """
    Mark a specific notification as read by its ID.
    """
    t0 = time.time()
    url = f"{_base()}/api/notifications/read/{notification_id}"
    try:
        resp = _httpx_request("POST", url, headers=_auth_headers())
        exec_time = (time.time() - t0) * 1000
        if resp.status_code == 200:
            return format_tool_response(
                success=True,
                message=f"Notification #{notification_id} marked as read.",
                data={"notification_id": notification_id},
                tool_name="mark_notification_read",
                exec_time_ms=exec_time,
            )
        return _fmt_error(resp, "Mark notification read", "mark_notification_read", exec_time)
    except httpx.ConnectError:
        return format_tool_response(
            success=False,
            message="Cannot connect to Xevyte backend.",
            tool_name="mark_notification_read",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="CONNECT_ERROR",
        )
    except Exception as e:
        return format_tool_response(
            success=False,
            message=f"Unexpected error: {str(e)}",
            tool_name="mark_notification_read",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="INTERNAL_ERROR",
        )


# ─── 14. Get holidays list ────────────────────────────────────────────────────
@tool
def get_holidays() -> str:
    """
    Get the list of company holidays for the current year.
    """
    t0 = time.time()
    cache_key = "get_holidays:all"
    cached_val = _cache.get(cache_key)
    if cached_val:
        return cached_val

    url = f"{_base()}/api/leaves/holidays"
    try:
        resp = _httpx_request("GET", url, headers=_auth_headers())
        exec_time = (time.time() - t0) * 1000
        if resp.status_code == 200:
            data = resp.json()
            res_json = format_tool_response(
                success=True,
                message=f"Company holiday list retrieved ({len(data) if data else 0} holidays).",
                data=data[:30] if data else [],
                tool_name="get_holidays",
                exec_time_ms=exec_time,
            )
            _cache.set(cache_key, res_json)
            return res_json
        return _fmt_error(resp, "Get holidays", "get_holidays", exec_time)
    except httpx.ConnectError:
        return format_tool_response(
            success=False,
            message="Cannot connect to Xevyte backend.",
            tool_name="get_holidays",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="CONNECT_ERROR",
        )
    except Exception as e:
        return format_tool_response(
            success=False,
            message=f"Unexpected error: {str(e)}",
            tool_name="get_holidays",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="INTERNAL_ERROR",
        )


# ─── 15. Get approved leave dates ────────────────────────────────────────────
@tool
def get_approved_leave_dates() -> str:
    """
    Get all approved leave dates for the logged-in employee.
    """
    t0 = time.time()
    emp_id = _current_employee_id.get()
    url = f"{_base()}/api/leaves/approved-dates/{emp_id}"
    try:
        resp = _httpx_request("GET", url, headers=_auth_headers())
        exec_time = (time.time() - t0) * 1000
        if resp.status_code == 200:
            data = resp.json()
            return format_tool_response(
                success=True,
                message=f"Approved leave dates retrieved for employee {emp_id}.",
                data=data if data else [],
                tool_name="get_approved_leave_dates",
                exec_time_ms=exec_time,
            )
        return _fmt_error(resp, "Get approved leave dates", "get_approved_leave_dates", exec_time)
    except httpx.ConnectError:
        return format_tool_response(
            success=False,
            message="Cannot connect to Xevyte backend.",
            tool_name="get_approved_leave_dates",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="CONNECT_ERROR",
        )
    except Exception as e:
        return format_tool_response(
            success=False,
            message=f"Unexpected error: {str(e)}",
            tool_name="get_approved_leave_dates",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="INTERNAL_ERROR",
        )


# ─── 16. Mark attendance ───────────────────────────────────────────────────────
@tool(args_schema=MarkAttendanceInput)
def mark_attendance(
    work_location: str,
    date: str = "",
    action: str = "check_in",
    client_name: str = "",
    project_name: str = "",
    remarks: str = "",
) -> str:
    """
    Mark attendance, check-in, or check-out for the logged-in employee.
    """
    t0 = time.time()
    if not work_location or not work_location.strip():
        return format_tool_response(
            success=False,
            message="Work location is required to mark attendance.",
            tool_name="mark_attendance",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="VALIDATION_ERROR",
        )

    if not date:
        date_iso = datetime.now().strftime("%Y-%m-%d")
    else:
        d_str = _to_backend_date(date)
        try:
            date_iso = datetime.strptime(d_str, "%d-%m-%Y").strftime("%Y-%m-%d")
        except Exception:
            date_iso = date

    now_time = datetime.now().strftime("%H:%M")
    emp_id = _current_employee_id.get()

    payload = {
        "date": date_iso,
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

    url = f"{_base()}/api/daily-entry/submit/{emp_id}"
    try:
        resp = _httpx_request("POST", url, json_data=payload, headers=_auth_headers())
        exec_time = (time.time() - t0) * 1000
        if resp.status_code in (200, 201):
            action_desc = "Check-in" if action == "check_in" else ("Check-out" if action == "check_out" else "Attendance")
            return format_tool_response(
                success=True,
                message=f"{action_desc} marked successfully for employee {emp_id}.",
                data=payload,
                tool_name="mark_attendance",
                exec_time_ms=exec_time,
            )
        return _fmt_error(resp, "Mark attendance", "mark_attendance", exec_time)
    except httpx.ConnectError:
        return format_tool_response(
            success=False,
            message="Cannot connect to Xevyte backend.",
            tool_name="mark_attendance",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="CONNECT_ERROR",
        )
    except Exception as e:
        return format_tool_response(
            success=False,
            message=f"Unexpected error: {str(e)}",
            tool_name="mark_attendance",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="INTERNAL_ERROR",
        )



# ─── 19. Get Allocations ──────────────────────────────────────────────────────
@tool
def get_my_allocations() -> str:
    """
    Get the project allocations for the logged-in employee.
    """
    t0 = time.time()
    emp_id = _current_employee_id.get()
    cache_key = f"get_my_allocations:{emp_id}"
    cached_val = _cache.get(cache_key)
    if cached_val:
        return cached_val

    url = f"{_base()}/api/allocations/employee/{emp_id}"
    try:
        resp = _httpx_request("GET", url, headers=_auth_headers())
        exec_time = (time.time() - t0) * 1000
        if resp.status_code == 200:
            data = resp.json()
            res_json = format_tool_response(
                success=True,
                message=f"Retrieved {len(data) if data else 0} allocations.",
                data=data,
                tool_name="get_my_allocations",
                exec_time_ms=exec_time,
            )
            _cache.set(cache_key, res_json)
            return res_json
        return _fmt_error(resp, "Get allocations", "get_my_allocations", exec_time)
    except Exception as e:
        return format_tool_response(False, str(e), tool_name="get_my_allocations", error_code="INTERNAL_ERROR")


# ─── 20. Update Personal Details ──────────────────────────────────────────────
@tool(args_schema=UpdatePersonalDetailsInput)
def update_personal_details(phone_number: str, emergency_contact: str, current_address: str, permanent_address: str, personal_mail: str = "") -> str:
    """
    Update the personal details (phone, emergency contact, address) of the logged-in employee.
    """
    t0 = time.time()
    emp_id = _current_employee_id.get()
    
    # In the Xevyte Spring Boot backend, these fields live on the main Employee entity, 
    # not the EmployeePersonalDetails table.
    url = f"{_base()}/api/employees/{emp_id}"
    
    payload = {
        "contactNo": phone_number,
        "emergencyContactNumber": emergency_contact,
        "presentAddress": current_address,
        "address": permanent_address,
        "personalMail": personal_mail
    }
    
    # We remove empty fields from payload to avoid nullifying existing data, 
    # but since this is a PUT we probably just send what we want to update.
    # Actually, EmployeeController.updateEmployeeProfile does a partial update check.
    
    try:
        resp = _httpx_request("PUT", url, json_data=payload, headers=_json_headers())
        exec_time = (time.time() - t0) * 1000
        if resp.status_code in (200, 204):
            _cache.invalidate(f"get_my_profile:{emp_id}")
            return format_tool_response(True, "Personal details updated successfully.", data=payload, tool_name="update_personal_details", exec_time_ms=exec_time)
        return _fmt_error(resp, "Update personal details", "update_personal_details", exec_time)
    except Exception as e:
        return format_tool_response(False, str(e), tool_name="update_personal_details", error_code="INTERNAL_ERROR")


# ─── 21. Update Bank Details ──────────────────────────────────────────────────
@tool(args_schema=UpdateBankDetailsInput)
def update_bank_details(bank_name: str, account_number: str, ifsc_code: str, uan_number: str = "", pf_member_id: str = "", esi_number: str = "", esi_dispensary: str = "") -> str:
    """
    Update the bank and statutory details (bank name, account number, IFSC code, UAN, PF, ESI) of the logged-in employee.
    """
    t0 = time.time()
    emp_id = _current_employee_id.get()
    url = f"{_base()}/api/employees/{emp_id}/bank-details"
    payload = {
        "bankName": bank_name,
        "bankAccountNumber": account_number,  # Updated to match entity field bankAccountNumber
        "bankIfscCode": ifsc_code,            # Updated to match entity field bankIfscCode
        "uanNumber": uan_number,
        "pfMemberId": pf_member_id,
        "esiNumber": esi_number,
        "esiDispensary": esi_dispensary
    }
    try:
        resp = _httpx_request("PUT", url, json_data=payload, headers=_json_headers())
        exec_time = (time.time() - t0) * 1000
        if resp.status_code in (200, 204):
            _cache.invalidate(f"get_my_profile:{emp_id}")
            return format_tool_response(True, "Bank & Statutory details updated successfully.", data=payload, tool_name="update_bank_details", exec_time_ms=exec_time)
        return _fmt_error(resp, "Update bank details", "update_bank_details", exec_time)
    except Exception as e:
        return format_tool_response(False, str(e), tool_name="update_bank_details", error_code="INTERNAL_ERROR")


# ─── 22. Get Nominees ───────────────────────────────────────────────────────────
@tool
def get_my_nominees() -> str:
    """
    Get the list of insurance nominees for the logged-in employee.
    """
    t0 = time.time()
    emp_id = _current_employee_id.get()
    cache_key = f"get_my_nominees:{emp_id}"
    cached_val = _cache.get(cache_key)
    if cached_val:
        return cached_val

    url = f"{_base()}/api/employees/{emp_id}/insurance-nominees"
    try:
        resp = _httpx_request("GET", url, headers=_auth_headers())
        exec_time = (time.time() - t0) * 1000
        if resp.status_code == 200:
            data = resp.json()
            res_json = format_tool_response(True, f"Retrieved {len(data) if data else 0} nominees.", data=data, tool_name="get_my_nominees", exec_time_ms=exec_time)
            _cache.set(cache_key, res_json)
            return res_json
        return _fmt_error(resp, "Get nominees", "get_my_nominees", exec_time)
    except Exception as e:
        return format_tool_response(False, str(e), tool_name="get_my_nominees", error_code="INTERNAL_ERROR")


# ─── 23. Add Nominee ────────────────────────────────────────────────────────────
@tool(args_schema=AddNomineeInput)
def add_nominee(nominee_name: str, relationship: str, date_of_birth: str) -> str:
    """
    Add a new insurance nominee for the logged-in employee.
    """
    t0 = time.time()
    emp_id = _current_employee_id.get()
    url = f"{_base()}/api/employees/{emp_id}/insurance-nominees"
    payload = {
        "nomineeName": nominee_name,
        "relationship": relationship,
        "dateOfBirth": date_of_birth
    }
    try:
        resp = _httpx_request("POST", url, json_data=payload, headers=_json_headers())
        exec_time = (time.time() - t0) * 1000
        if resp.status_code in (200, 201):
            _cache.invalidate(f"get_my_nominees:{emp_id}")
            return format_tool_response(True, f"Successfully added nominee: {nominee_name}.", data=payload, tool_name="add_nominee", exec_time_ms=exec_time)
        return _fmt_error(resp, "Add nominee", "add_nominee", exec_time)
    except Exception as e:
        return format_tool_response(False, str(e), tool_name="add_nominee", error_code="INTERNAL_ERROR")


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
    get_my_allocations,
    update_personal_details,
    update_bank_details,
    get_my_nominees,
    add_nominee,
]
