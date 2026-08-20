"""
XEVYTE-AGENT Enhanced Tools Module
Provides: API catalog search, HR RAG retrieval, API execution with confirmations
"""

import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from dateutil import parser
import httpx
from app.config import get_settings
from app.agent.confirmation import generate_confirmation_token

logger = logging.getLogger("xeva.agent.tools")

# ============================================================================
# CATALOG MANAGEMENT
# ============================================================================

class APIECatalog:
    """Load and search the API catalog"""
    
    _catalog = None
    
    @classmethod
    def load(cls):
        """Load catalog from JSON"""
        if cls._catalog is None:
            try:
                settings = get_settings()
                with open(settings.CATALOG_PATH, "r") as f:
                    cls._catalog = json.load(f)
            except FileNotFoundError:
                logger.error("Catalog not found. Using empty catalog.")
                cls._catalog = {"modules": {}}
        return cls._catalog
    
    @classmethod
    def get_endpoint(cls, endpoint_id: str) -> Optional[Dict]:
        """Fetch endpoint details by ID"""
        catalog = cls.load()
        for module_name, module_data in catalog.get("modules", {}).items():
            for endpoint in module_data.get("endpoints", []):
                if endpoint.get("endpoint_id") == endpoint_id:
                    return endpoint
        return None
    
    @classmethod
    def search_by_intent(cls, query: str) -> List[Dict]:
        """Search endpoints by natural language intent"""
        catalog = cls.load()
        query_lower = query.lower()
        results = []
        
        # Score and rank results
        scored_results = []
        for module_name, module_data in catalog.get("modules", {}).items():
            for endpoint in module_data.get("endpoints", []):
                score = 0
                description = endpoint.get("description", "").lower()
                
                # Keyword matching
                if query_lower in description:
                    score += 10
                
                # Partial word matching
                query_words = query_lower.split()
                for word in query_words:
                    if word in description:
                        score += 5
                
                if score > 0:
                    scored_results.append((score, endpoint))
        
        # Return top 5 sorted by score
        scored_results.sort(key=lambda x: x[0], reverse=True)
        return [ep for _, ep in scored_results[:5]]
    
    @classmethod
    def to_tool_description(cls, endpoint: Dict) -> str:
        """Format endpoint as tool description for LLM"""
        return f"""
**{endpoint['description']}** (ID: {endpoint['endpoint_id']})
- Method: {endpoint['method']}
- Path: {endpoint['path']} (If the path contains {{variables}} OTHER THAN {{employeeId}} or {{managerId}}, you MUST provide them in the `path_params` dictionary. {{employeeId}} and {{managerId}} are auto-injected.)
- Required: {', '.join(endpoint.get('required_fields', []))}
- Optional: {', '.join(endpoint.get('optional_fields', []))}
- Confirmation: {'Yes' if endpoint.get('requires_confirmation') else 'No'}
"""


# ============================================================================
# TOOL: SEARCH API CATALOG
# ============================================================================

def search_api_catalog(query: str) -> str:
    """
    Tool: Search the API catalog for relevant endpoints.
    User calls this to find the right API for their intent.
    """
    logger.info(f"Searching catalog for: {query}")
    catalog = APIECatalog()
    results = catalog.search_by_intent(query)
    
    if not results:
        return "No matching endpoints found. Please be more specific about what you're trying to do."
    
    output = "Found the following relevant endpoints:\n\n"
    for endpoint in results:
        output += catalog.to_tool_description(endpoint)
    
    output += "\nIf multiple endpoints seem equally relevant and you are not absolutely certain which one the user intended, DO NOT guess. Instead, ASK the user a clarifying question before calling call_xevyte_api."
    return output


# ============================================================================
# TOOL: SEARCH HR KNOWLEDGE BASE (RAG)
# ============================================================================

def search_hr_knowledge_base(query: str) -> str:
    """
    Tool: Search HR policies using RAG system.
    User asks policy questions; agent retrieves company-specific policies.
    """
    logger.info(f"Searching HR KB for: {query}")
    
    # Read the local handbook file as a simple "RAG" substitute
    settings = get_settings()
    try:
        import os
        policy_path = os.path.join(settings.RAG_POLICIES_DIR, "handbook.md")
        with open(policy_path, "r") as f:
            content = f.read()
        return f"Found relevant HR policy information:\n\n{content}"
    except Exception as e:
        logger.error(f"Failed to read HR policies: {e}")
        return "Sorry, I could not access the HR knowledge base at this moment."


# ============================================================================
# DATE UTILITIES
# ============================================================================

def resolve_relative_date(date_input: str, format_output: str = "yyyy-MM-dd") -> str:
    """
    Convert relative dates (today, tomorrow, next monday) to absolute date.
    
    Args:
        date_input: "today", "tomorrow", "next monday", or actual date
        format_output: "dd-MM-yyyy" or "yyyy-MM-dd"
    
    Returns:
        Formatted date string
    """
    date_input = date_input.lower().strip()
    
    try:
        # Try parsing as actual date first
        parsed = parser.parse(date_input)
    except:
        # Handle relative dates
        today = datetime.now().date()
        
        if date_input == "today":
            parsed = today
        elif date_input == "tomorrow":
            parsed = today + timedelta(days=1)
        elif date_input.startswith("next "):
            day_name = date_input.replace("next ", "").capitalize()
            # Find next occurrence of day
            days = {
                "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
                "Friday": 4, "Saturday": 5, "Sunday": 6
            }
            if day_name in days:
                target_day = days[day_name]
                current_day = today.weekday()
                days_ahead = target_day - current_day
                if days_ahead <= 0:
                    days_ahead += 7
                parsed = today + timedelta(days=days_ahead)
            else:
                raise ValueError(f"Unknown day: {day_name}")
        elif " days" in date_input or " weeks" in date_input:
            import re
            match = re.search(r"(\d+)\s+(days|weeks)", date_input)
            if match:
                num = int(match.group(1))
                unit = match.group(2)
                delta_days = num if unit == "days" else num * 7
                parsed = today + timedelta(days=delta_days)
            else:
                raise ValueError(f"Cannot parse: {date_input}")
        else:
            raise ValueError(f"Unknown date format: {date_input}")
    
    # Convert to datetime if needed
    if isinstance(parsed, str):
        parsed = parser.parse(parsed).date()
    elif hasattr(parsed, 'date'):
        parsed = parsed.date()
    
    # Format output
    if format_output == "dd-MM-yyyy":
        return parsed.strftime("%d-%m-%Y")
    else:  # yyyy-MM-dd
        return parsed.strftime("%Y-%m-%d")


# ============================================================================
# TOOL: CALL XEVYTE API (WITH CONFIRMATION WORKFLOW)
# ============================================================================

async def call_xevyte_api(
    endpoint_id: str,
    user_context: Dict[str, Any],
    method: str = None,
    path: str = None,
    path_params: Optional[Dict[str, Any]] = None,
    query_params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Tool: Execute API call to Xevyte Connect backend.
    
    WORKFLOW FOR MUTATIONS (POST/PUT/DELETE):
    1. Intercept the call
    2. Generate confirmation token with encrypted payload
    3. Return pending status (don't execute yet)
    4. Frontend shows summary and "Approve" button
    5. When approved, execute the call with token
    
    WORKFLOW FOR READS (GET):
    1. Execute immediately
    2. Return results
    
    Args:
        endpoint_id: Fast-path ID (e.g., 'applyLeave')
        user_context: {employeeId, tenantId, role, ...}
        method, path: Auto-resolved from catalog if not provided
        path_params: {employeeId}, {leaveId}, etc.
        query_params: date range, filters
        body: Payload for POST/PUT
        token: JWT bearer token
    """
    
    # ========================================================================
    # STEP 1: Resolve endpoint details from catalog
    # ========================================================================
    
    endpoint_data = APIECatalog().get_endpoint(endpoint_id)
    
    if not endpoint_data:
        return {
            "status": "error",
            "error": f"Endpoint '{endpoint_id}' not found in catalog",
            "suggestion": f"Try: search_api_catalog('...')"
        }
    
    # Always use the catalog's truth for method and path to prevent LLM hallucinations
    method = endpoint_data.get("method", "GET").upper()
    path = endpoint_data.get("path", "")
    
    # ========================================================================
    # STEP 2: Resolve path parameters
    # ========================================================================
    
    logger.error(f"====== ARGS: endpoint={endpoint_id}, path_params={path_params}, body={body}, query_params={query_params}"); actual_path = path
    if path_params:
        for key, value in path_params.items():
            actual_path = actual_path.replace(f"{{{key}}}", str(value))
        
        # Fallback: if LLM provided "id" but the path expected {leaveId}, {claimId}, etc.
        if "{" in actual_path and "id" in path_params:
            import re
            actual_path = re.sub(r"\{[^}]+\}", str(path_params["id"]), actual_path, count=1)
    
    # Second Fallback: if LLM put the ID in the body instead of path_params
    if "{" in actual_path and body:
        for k, v in body.items():
            if "id" in k.lower():
                import re
                actual_path = re.sub(r"\{[^}]+\}", str(v), actual_path, count=1)
                break
    
    # Auto-inject employeeId and managerId if missing
    if "{employeeId}" in actual_path and user_context.get("employeeId"):
        actual_path = actual_path.replace(
            "{employeeId}", 
            user_context["employeeId"]
        )
    if "{managerId}" in actual_path and user_context.get("employeeId"):
        actual_path = actual_path.replace(
            "{managerId}", 
            user_context["employeeId"]
        )
    
    # ========================================================================
    # STEP 3: Validate required fields
    # ========================================================================
    
    required_fields = endpoint_data.get("required_fields", [])
    
    # Special handling for Weekly Hours Overview
    
    # Special handling for Deep Analytics (requires startDate and endDate)
    if endpoint_id == "getDeepAnalytics":
        from datetime import date, timedelta
        today = date.today()
        start = today - timedelta(days=30)
        query_params = query_params or {}
        if "startDate" not in query_params:
            query_params["startDate"] = start.strftime("%Y-%m-%d")
        if "endDate" not in query_params:
            query_params["endDate"] = today.strftime("%Y-%m-%d")

    if endpoint_id == "getMyWeeklyHours":
        from datetime import date, timedelta
        today = date.today()
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        query_params = query_params or {}
        query_params["startDate"] = start.strftime("%Y-%m-%d")
        query_params["endDate"] = end.strftime("%Y-%m-%d")

    if body and endpoint_id not in ("submitEntry", "updateEntry", "applyLeave"): # These fields will be auto-injected
        missing = [f for f in required_fields if f not in body and f != "employeeId"]
        if missing:
            return {
                "status": "incomplete",
                "error": f"Missing required fields: {', '.join(missing)}",
                "endpoint_id": endpoint_id
            }
    
    # ========================================================================
    
    # Special handling for Recent Activities Aggregator
    
    if endpoint_id == "getMyUnifiedTasks":
        tasks = WorkflowHelpers.build_my_tasks(user_context, token)
        return json.dumps(tasks)

    if endpoint_id == "getRecentActivities":
        try:
            return await WorkflowHelpers.build_recent_activities(user_context, token)
        except Exception as e:
            return {"status": "error", "error": f"Failed to get activities: {e}"}

    # STEP 4: Handle mutations (POST/PUT/DELETE/PATCH)
    # ========================================================================
    
    if method in ("POST", "PUT", "DELETE", "PATCH"):
        
        # Special handling for Check-In (submitEntry)
        if endpoint_id == "submitEntry" and method == "POST" and body:
            try:
                body = await WorkflowHelpers.build_checkin_payload(user_context, token, body)
            except Exception as e:
                logger.error(f"Failed to build check-in payload: {e}")
                return {
                    "status": "error",
                    "error": f"Could not auto-populate profile details for check-in: {e}"
                }
        
        # Special handling for Check-Out (updateEntry)
        if endpoint_id == "updateEntry" and method == "PUT" and body:
            emp_id = user_context.get("employeeId")
            entry_id_str = actual_path.split("/")[-1]
            if emp_id and entry_id_str:
                try:
                    body = await WorkflowHelpers.build_checkout_payload(user_context, token, entry_id_str, body)
                except Exception as e:
                    logger.error(f"Failed to build check-out payload: {e}")
                    return {
                        "status": "error",
                        "error": f"Could not process check-out: {e}"
                    }
                    
        # Special handling for Leave Application (applyLeave)
        if endpoint_id == "applyLeave" and method == "POST" and body:
            try:
                leave_result = await WorkflowHelpers.collect_leave_data(
                    user_context, token,
                    body.get("startDate", ""),
                    body.get("endDate", ""),
                    body.get("leaveTypeId", ""),
                    body.get("reason", "Personal reasons")
                )
                if leave_result.get("error"):
                    return {
                        "status": "error",
                        "error": leave_result["error"]
                    }
                body = leave_result["payload"]
            except Exception as e:
                logger.error(f"Failed to build leave payload: {e}")
                return {
                    "status": "error",
                    "error": f"Could not process leave application: {e}"
                }
        
        # Intercept mutation for user confirmation
        settings = get_settings()
        if settings.ENABLE_CONFIRMATIONS and endpoint_id not in ("submitEntry", "updateEntry"):
            action_data = {
                "endpoint_id": endpoint_id,
                "method": method,
                "path": actual_path,
                "query_params": query_params,
                "body": body
            }
            emp_id = user_context.get("employeeId", "unknown")
            confirm_token = generate_confirmation_token(action_data, emp_id)
            
            return {
                "status": "pending_confirmation",
                "pending_confirmation_token": confirm_token,
                "summary": f"Ready to execute {method} on {actual_path}",
                "body": body
            }
    
    # ========================================================================
    # STEP 5: Execute read requests immediately
    # ========================================================================
    
    settings = get_settings()
    url = f"{settings.JAVA_BACKEND_URL}{actual_path}"
    
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    # Add tenant ID if required
    if endpoint_data.get("headers_required"):
        headers["X-Tenant-ID"] = user_context.get("tenantId", "")
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            request_kwargs = {
                "url": url,
                "headers": headers,
            }
            
            if query_params:
                request_kwargs["params"] = query_params
            
            if body and method != "GET":
                request_kwargs["json"] = body
            
            response = await client.request(method, **request_kwargs)
            
            # ================================================================
            # STEP 6: Parse response
            # ================================================================
            
            try:
                resp_data = response.json()
            except ValueError:
                resp_data = response.text
            
            # Success response
            if response.status_code in (200, 201, 204):
                return {
                    "status": "success",
                    "status_code": response.status_code,
                    "data": resp_data
                }
            
            # Error response
            else:
                error_msg = resp_data.get("message") if isinstance(resp_data, dict) else str(resp_data)
                
                return {
                    "status": "error",
                    "status_code": response.status_code,
                    "error": error_msg,
                    "suggestion": _get_error_suggestion(response.status_code, endpoint_id)
                }
    
    except httpx.TimeoutException:
        return {
            "status": "error",
            "error": "Request timed out. Try again in a moment.",
            "endpoint_id": endpoint_id
        }
    
    except Exception as e:
        logger.error(f"API call failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "endpoint_id": endpoint_id
        }


# ============================================================================
# HELPER: Generate error suggestion
# ============================================================================

def _get_error_suggestion(status_code: int, endpoint_id: str) -> str:
    """Provide context-specific error messages"""
    
    if status_code == 400:
        return "Invalid input. Please check dates, formats, and required fields."
    elif status_code == 401:
        return "Authentication failed. Please log in again."
    elif status_code == 403:
        return f"You don't have permission for this action. Contact HR if needed."
    elif status_code == 404:
        return "Resource not found. The item may have been deleted or doesn't exist."
    elif status_code == 500:
        return "Server error. Contact support if the problem persists."
    else:
        return f"Unexpected error (code {status_code}). Try again or contact support."


# ============================================================================
# MULTI-STEP WORKFLOW HELPERS
# ============================================================================

class WorkflowHelpers:
    @staticmethod
    def build_my_tasks(user_context: dict, token: str) -> list:
        emp_id = user_context.get("employeeId")
        headers = {"Authorization": f"Bearer {token}"}
        tasks = []
        
        try:
            # 1. Leaves
            
            r_leaves = httpx.get(f"{get_settings().JAVA_BACKEND_URL}/api/leaves/manager/{emp_id}", headers=headers, timeout=5.0)
            if r_leaves.status_code == 200:
                data = r_leaves.json()
                logger.info(f"LEAVES DATA: {data}")
                for l in data:

                    if "pending" in str(l.get("status")).lower():
                        tasks.append({
                            "ID": l.get("id"),
                            "Type": "Leave Approval",
                            "Employee": l.get("employeeName"),
                            "Details": f"{l.get('leaveType')} from {l.get('startDate')} to {l.get('endDate')}",
                            "Date": l.get("createdAt", "N/A")
                        })
            
            # 2. Claims
            r_claims = httpx.get(f"{get_settings().JAVA_BACKEND_URL}/api/claims/manager/{emp_id}", headers=headers, timeout=5.0)
            if r_claims.status_code == 200:
                for c in r_claims.json():
                    if "pending" in str(c.get("status")).lower():
                        tasks.append({
                            "ID": c.get("id"),
                            "Type": "Claim Approval",
                            "Employee": c.get("employeeName"),
                            "Details": f"{c.get('expenseType')} - {c.get('amount')}",
                            "Date": c.get("appliedOn", "N/A")
                        })
            
            # 3. Travel
            r_travel = httpx.get(f"{get_settings().JAVA_BACKEND_URL}/api/travel/manager/pending/{emp_id}", headers=headers, timeout=5.0)
            if r_travel.status_code == 200:
                for t in r_travel.json():
                    tasks.append({
                        "ID": t.get("id"),
                        "Type": "Travel Approval",
                        "Employee": t.get("employeeName"),
                        "Details": f"{t.get('purpose')} to {t.get('destination')}",
                        "Date": t.get("requestDate", "N/A")
                    })
            
            
            # 5. Exit/Resignation Tasks
            try:
                r_exits = httpx.get(f"{get_settings().JAVA_BACKEND_URL}/v1/exit-management/manager/pending-resignations", headers=headers, timeout=5.0)
                if r_exits.status_code == 200:
                    for ex in r_exits.json():
                        if ex.get("status") != "Final Approved - Exit Complete":
                            tasks.append({
                                "ID": ex.get("id"),
                                "Type": "Exit/Resignation Approval",
                                "Employee": ex.get("employeeName", "Unknown"),
                                "Details": f"Resignation Date: {ex.get('resignationDate', 'N/A')}",
                                "Date": ex.get("createdDate", "N/A")
                            })
            except Exception as e:
                logger.warning(f"Could not fetch exit tasks: {e}")

            # 4. Tickets
            r_tickets = httpx.get(f"{get_settings().JAVA_BACKEND_URL}/api/tickets/manager/{emp_id}", headers=headers, timeout=5.0)
            if r_tickets.status_code == 200:
                for tk in r_tickets.json():
                    if "pending" in str(tk.get("status")).lower() or "open" in str(tk.get("status")).lower():
                        tasks.append({
                            "ID": tk.get("id"),
                            "Type": "Ticket Approval",
                            "Employee": tk.get("employeeName", tk.get("employeeId", "Unknown")),
                            "Details": tk.get("title", tk.get("subject", "N/A")),
                            "Date": tk.get("createdAt", "N/A")
                        })
        except Exception as e:
            logger.error(f"Error building my tasks: {e}")
            
        return tasks


    @staticmethod
    async def build_recent_activities(user_context: dict, token: str) -> dict:
        """Mock the React UI's recent activities aggregator"""
        emp_id = user_context.get("employeeId")
        if not emp_id:
            return {"status": "error", "error": "Missing employeeId"}
        
        settings = get_settings()
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        
        activities = []
        try:
            async with httpx.AsyncClient() as client:
                # Fetch Leaves
                leaves_resp = await client.get(f"{settings.JAVA_BACKEND_URL}/api/leaves/employee/{emp_id}", headers=headers)
                if leaves_resp.status_code == 200:
                    for leave in leaves_resp.json():
                        activities.append({
                            "Date & Time": leave.get("createdAt", ""),
                            "Action Type": "LEAVE",
                            "Description": f"Leave {leave.get('status', 'PENDING').lower()} for {leave.get('totalDays', 1)} day(s)"
                        })
                
                # Fetch Tickets
                tickets_resp = await client.get(f"{settings.JAVA_BACKEND_URL}/api/tickets/my-tickets/{emp_id}", headers=headers)
                if tickets_resp.status_code == 200:
                    for ticket in tickets_resp.json():
                        activities.append({
                            "Date & Time": ticket.get("createdAt", ""),
                            "Action Type": "TICKET",
                            "Description": f"Ticket {ticket.get('status', 'OPEN').lower()}: {ticket.get('title', '')}"
                        })
        except Exception as e:
            logger.error(f"Failed to aggregate activities: {e}")
            pass
            
        if not activities:
            return {"status": "success", "status_code": 200, "data": "No recent activities found."}
            
        return {"status": "success", "status_code": 200, "data": activities[:5]}


    """Reusable multi-step workflow logic"""
    
    @staticmethod
    async def collect_leave_data(
        user_context: Dict,
        token: str,
        start_date_str: str,
        end_date_str: str,
        leave_type_id: str,
        reason: str = None
    ) -> Dict:
        """
        Multi-step workflow for leave application:
        1. Fetch leave balance
        2. Validate dates and policy
        3. Return collected payload
        """
        
        # Resolve dates to dd-MM-yyyy format (required by Leave APIs)
        start_date = resolve_relative_date(start_date_str, "dd-MM-yyyy")
        end_date = resolve_relative_date(end_date_str, "dd-MM-yyyy")
        
        # Fetch leave balance
        balance_result = await call_xevyte_api(
            endpoint_id="getDetailedLeaveBalance",
            user_context=user_context,
            token=token
        )
        
        if balance_result["status"] != "success":
            return {"error": "Could not fetch leave balance"}
        
        # Check available balance for leave type
        balances = balance_result["data"].get("leaveBalances", [])
        leave_type_balance = next(
            (b for b in balances if b["leaveType"] == leave_type_id),
            None
        )
        
        if not leave_type_balance:
            return {"error": f"Leave type {leave_type_id} not found"}
        
        if leave_type_balance["available"] <= 0:
            return {"error": "No leave balance available"}
        
        return {
            "status": "ready",
            "payload": {
                "employeeId": user_context.get("employeeId"),
                "leaveTypeId": leave_type_id,
                "startDate": start_date,
                "endDate": end_date,
                "reason": reason or "Personal work"
            },
            "balance_available": leave_type_balance["available"]
        }

    @staticmethod
    async def build_checkin_payload(user_context: Dict, token: str, partial_body: Dict) -> Dict:
        """
        Takes partial inputs (workLocation, clientName, projectName, remarks)
        and auto-populates exact time, employee, manager, and HR details.
        """
        emp_id = user_context.get("employeeId")
        if not emp_id:
            raise ValueError("Employee ID missing from context.")
            
        import datetime
        now = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
            
        payload = {
            "employeeId": emp_id,
            "date": date_str,
            "loginTime": time_str,
            "status": "CHECKED_IN",
            "frozen": False,
            "workLocation": partial_body.get("workLocation", "OFFICE"),
            "loginWorkLocation": partial_body.get("workLocation", "OFFICE"),
            "remarks": partial_body.get("remarks", ""),
            "clientName": partial_body.get("clientName", ""),
            "projectName": partial_body.get("projectName", ""),
            "clientId": partial_body.get("clientId", 0),
            "projectId": partial_body.get("projectId", 0),
        }
        
        # Fetch employee overview to populate full details
        settings = get_settings()
        url = f"{settings.JAVA_BACKEND_URL}/api/organization-overview/{emp_id}"
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
            
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    profile = resp.json()
                    payload["employeeFirstName"] = profile.get("firstName", "Unknown")
                    payload["employeeLastName"] = profile.get("lastName", "")
                    
                    manager = profile.get("reportingManager", {})
                    if manager:
                        payload["managerId"] = manager.get("employeeId", "")
                        payload["managerFirstName"] = manager.get("firstName", "")
                        payload["managerLastName"] = manager.get("lastName", "")
                    
                    hr = profile.get("hrManager", {})
                    if hr:
                        payload["hrId"] = hr.get("employeeId", "")
                        payload["hrFirstName"] = hr.get("firstName", "")
                        payload["hrLastName"] = hr.get("lastName", "")
        except Exception as e:
            logger.warning(f"Could not fetch profile details for check-in: {e}")
            
        return payload

    @staticmethod
    async def build_checkout_payload(user_context: Dict, token: str, entry_id: str, partial_body: Dict) -> Dict:
        """
        Takes partial inputs (remarks, location) for check-out, fetches the morning's
        entry, merges them, calculates logout time and total hours, and returns the full payload.
        """
        emp_id = user_context.get("employeeId")
        if not emp_id:
            raise ValueError("Employee ID missing from context.")
            
        import datetime
        now = datetime.datetime.now()
        time_str = now.strftime("%H:%M:%S")
        
        # 1. Fetch the existing entry
        settings = get_settings()
        url = f"{settings.JAVA_BACKEND_URL}/api/daily-entry/employee/{emp_id}"
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
            
        existing_entry = None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    entries = resp.json()
                    for e in entries:
                        if str(e.get("id")) == str(entry_id):
                            existing_entry = e
                            break
        except Exception as e:
            logger.warning(f"Failed to fetch existing entry {entry_id} for check-out merge: {e}")
            
        if not existing_entry:
            raise ValueError(f"Could not find today's check-in entry with ID {entry_id}")
            
        # 2. Merge user-provided fields
        payload = dict(existing_entry)
        
        # Override remarks if provided
        if partial_body.get("remarks"):
            payload["remarks"] = partial_body["remarks"]
            
        # Override logout work location if provided, else default to loginWorkLocation
        if partial_body.get("workLocation"):
            payload["logoutWorkLocation"] = partial_body["workLocation"]
        elif not payload.get("logoutWorkLocation"):
            payload["logoutWorkLocation"] = payload.get("loginWorkLocation", "OFFICE")
            
        # 3. Calculate hours
        payload["logoutTime"] = time_str
        payload["status"] = "CHECKED_OUT"
        
        try:
            login_time_str = payload.get("loginTime")
            if login_time_str:
                login_dt = datetime.datetime.strptime(login_time_str, "%H:%M:%S")
                logout_dt = datetime.datetime.strptime(time_str, "%H:%M:%S")
                diff = logout_dt - login_dt
                hours = diff.total_seconds() / 3600.0
                payload["totalHours"] = round(hours, 2)
        except Exception as e:
            logger.warning(f"Failed to calculate totalHours during checkout: {e}")
            payload["totalHours"] = 0.0
            
        return payload
        



# ============================================================================
# EXPORT ALL TOOLS
# ============================================================================

__all__ = [
    "search_api_catalog",
    "search_hr_knowledge_base",
    "call_xevyte_api",
    "resolve_relative_date",
    "APIECatalog",
    "WorkflowHelpers"
]
