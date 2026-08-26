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
        """Search endpoints by natural language intent with comprehensive indexing and intent alignment"""
        catalog = cls.load()
        query_lower = query.lower()
        query_words = [w for w in query_lower.split() if len(w) > 2]
        
        # Synonym expansion
        expanded_words = list(query_words)
        for w in query_words:
            if w in ("client", "clients"):
                expanded_words.extend(["customer", "customers"])
            elif w in ("customer", "customers"):
                expanded_words.extend(["client", "clients"])
            elif w in ("laptop", "equipment", "hardware", "device"):
                expanded_words.extend(["asset", "assets"])
            elif w in ("ticket", "tickets", "incident", "issue"):
                expanded_words.extend(["helpdesk", "support"])

        # Intent verb categories
        is_create_intent = any(w in query_lower for w in ["create", "add", "register", "new", "submit", "apply", "raise", "file"])
        is_update_intent = any(w in query_lower for w in ["update", "edit", "modify", "change", "renew", "save", "approve", "reject", "cancel", "resolve", "punch"])
        is_view_intent = any(w in query_lower for w in ["show", "list", "view", "get", "fetch", "check", "my", "all", "history", "balance", "status", "who", "which"])

        scored_results = []
        for module_name, module_data in catalog.get("modules", {}).items():
            for endpoint in module_data.get("endpoints", []):
                score = 0
                ep_id = endpoint.get("endpoint_id", "").lower()
                method = endpoint.get("method", "GET").upper()
                path = endpoint.get("path", "").lower()
                desc = endpoint.get("description", "").lower()
                ui_name = endpoint.get("ui_name", "").lower()
                user_intent = endpoint.get("user_intent", "").lower()
                cap = endpoint.get("capability", "").lower()
                mod_name = str(module_name).lower()
                
                searchable_text = f"{ep_id} {path} {desc} {ui_name} {user_intent} {cap} {mod_name}"
                
                # Exact phrase match
                if query_lower in searchable_text:
                    score += 35
                
                # Keyword matches
                for word in expanded_words:
                    if word in ep_id:
                        score += 25
                    if word in path:
                        score += 20
                    if word in user_intent:
                        score += 20
                    if word in desc:
                        score += 10
                    if word in mod_name or word in ui_name or word in cap:
                        score += 15

                # Intent verb alignment
                if is_create_intent:
                    if method == "POST" or any(w in ep_id for w in ["create", "submit", "register", "apply", "add"]):
                        score += 35
                    elif method == "GET":
                        score -= 20
                elif is_update_intent:
                    if method in ("PUT", "PATCH") or any(w in ep_id for w in ["update", "modify", "cancel", "approve", "reject", "resolve"]):
                        score += 35
                    elif method == "GET":
                        score -= 15
                elif is_view_intent:
                    if method == "GET":
                        score += 25
                    elif method in ("DELETE",):
                        score -= 30
                
                if score > 0:
                    scored_results.append((score, endpoint))
        
        # Sort by score descending and deduplicate by endpoint_id
        scored_results.sort(key=lambda x: x[0], reverse=True)
        seen = set()
        unique_results = []
        for _, ep in scored_results:
            eid = ep.get("endpoint_id")
            if eid not in seen:
                seen.add(eid)
                unique_results.append(ep)
                if len(unique_results) >= 6:
                    break
        return unique_results
    
    @classmethod
    def to_tool_description(cls, endpoint: Dict) -> str:
        """Format endpoint as tool description for LLM"""
        import re
        path = endpoint.get('path', '')
        path_vars = [v for v in re.findall(r'\{(.*?)\}', path) if v not in ['employeeId', 'managerId']]
        path_params_str = f"- Required Path Params (put in `path_params`): {', '.join(path_vars)}\n" if path_vars else ""
        
        return f"""
**Tool Name:** {endpoint.get('api_name', endpoint['endpoint_id'])} (ID: {endpoint['endpoint_id']})
**Description:** {endpoint['description']}
**HTTP Method:** {endpoint.get('method', 'GET')}
**URL Path:** {path}
**Input Schema:**
{path_params_str}- Required Fields: {', '.join(endpoint.get('required_fields', [])) or 'None'}
**Optional Tags:**
- Roles Allowed: {', '.join(endpoint.get('roles', [])) or 'All'}
- Module: {endpoint.get('ui_name', 'System')}
- Requires Confirmation: {endpoint.get('requires_confirmation', False)}
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
    
    output += "\nCRITICAL RULES:\n"
    output += "1. If the top result clearly matches the user's intent (e.g., 'search customer' → getAllCustomers, 'my assigned clients' → getCustomersForEmployee), IMMEDIATELY call that endpoint. DO NOT ask the user to choose.\n"
    output += "2. Only ask a clarifying functional question if the user's intent is genuinely ambiguous between DIFFERENT actions (e.g., 'leave' could mean apply or check balance).\n"
    output += "3. NEVER expose API endpoints, endpoint IDs, path URLs, or JSON keys in your response to the user!\n"
    output += "4. For customer/client queries: use getAllCustomers to list/search, getCustomerById for a specific customer, getCustomersForEmployee for assigned clients."
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


async def analyze_document_from_url(
    document_url: str,
    question: str,
    auth_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Tool: In-Memory Advanced Document RAG.
    Streams any PDF, DOCX, XLSX, or Receipt from Java HRMS directly into memory and
    answers user questions with exact figures and page citations without saving
    any file to disk or database.
    """
    from app.rag.doc_rag import answer_question_from_document_stream
    return await answer_question_from_document_stream(document_url, question, auth_token)


async def summarize_document_from_url(
    document_url: str,
    focus_area: Optional[str] = None,
    auth_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Tool: In-Memory Document Summarizer.
    Streams any document from Java HRMS into memory and returns a structured executive summary.
    """
    from app.rag.doc_rag import summarize_document_from_stream
    return await summarize_document_from_stream(document_url, focus_area, auth_token)



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
    
    token = token or (user_context or {}).get("jwt_token") or (user_context or {}).get("token")
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
    
    # Special pre-processing for customer path parameters (resolve CID1 -> 1, or client name -> 1)
    if "/api/customers" in actual_path and "{id}" in actual_path:
        path_params = path_params or {}
        raw_id = None
        for k in ["id", "customerId", "customer_id", "name", "customerName"]:
            if k in path_params and path_params[k]:
                raw_id = str(path_params[k]).strip()
                break
            elif body and isinstance(body, dict) and k in body and body[k]:
                raw_id = str(body[k]).strip()
                break

        if raw_id:
            clean_id = raw_id.upper().replace("CID", "").strip()
            if clean_id.isdigit():
                path_params["id"] = clean_id
                actual_path = actual_path.replace("{id}", clean_id)
            else:
                # Resolve client name -> numeric ID from GET /api/customers
                try:
                    settings = get_settings()
                    tenant_id = (user_context or {}).get("tenantId", "scaloz")
                    r_all = httpx.get(
                        f"{settings.JAVA_BACKEND_URL}/api/customers",
                        headers={"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id},
                        timeout=5.0
                    )
                    if r_all.status_code == 200:
                        custs = r_all.json()
                        matched = next((c for c in custs if raw_id.lower() in str(c.get("customerName", "")).lower()), None)
                        if matched:
                            num_id = str(matched.get("customerId") or matched.get("id") or matched.get("tenantCustomerId") or "")
                            if num_id and num_id.isdigit():
                                path_params["id"] = num_id
                                actual_path = actual_path.replace("{id}", num_id)
                except Exception as e:
                    logger.warning(f"Failed to resolve customer by name: {e}")

    if path_params:
        for key, value in path_params.items():
            actual_path = actual_path.replace(f"{{{key}}}", str(value))
        
        # Fallback: if LLM provided "id" but the path expected {leaveId}, {claimId}, etc.
        if "{" in actual_path and "id" in path_params:
            import re
            actual_path = re.sub(r"\{[^}]+\}", str(path_params["id"]), actual_path, count=1)
    
    
    # Auto-inject employeeId, managerId, userId if missing
    if "{employeeId}" in actual_path and user_context.get("employeeId"):
        actual_path = actual_path.replace("{employeeId}", user_context["employeeId"])
    if "{managerId}" in actual_path and user_context.get("employeeId"):
        actual_path = actual_path.replace("{managerId}", user_context["employeeId"])
    if "{userId}" in actual_path and user_context.get("employeeId"):
        actual_path = actual_path.replace("{userId}", user_context["employeeId"])
        
    # Extract path params from body if the LLM misplaced them (e.g. {id} but LLM put claimId in body)
    if "{" in actual_path and body:
        import re
        for match in re.finditer(r"\{([^}]+)\}", actual_path):
            param_name = match.group(1)
            # Try exact match or common ID field variations
            possible_keys = [
                param_name, 
                f"{param_name}Id", 
                f"{endpoint_id.replace('approve', '').replace('reject', '').lower()}Id",
                "claimId", "leaveId", "leaveRequestId", "ticketId", "id"
            ]
            for pk in possible_keys:
                if body.get(pk) is not None:
                    actual_path = actual_path.replace(f"{{{param_name}}}", str(body[pk]))
                    break
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

    # Auto-inject employeeId into body if it's missing but required by the endpoint
    if body is not None and "employeeId" in required_fields and "employeeId" not in body:
        emp_id = user_context.get("employeeId")
        if emp_id:
            body["employeeId"] = emp_id

    # Special handling for claim approve/reject: Java expects role and approverId as query params
    if endpoint_id in ("approveClaim", "rejectClaim"):
        query_params = query_params or {}
        # Auto-inject role — Java claim controller strictly requires PascalCase "Manager" or "Finance"
        emp_id = user_context.get("employeeId")
        resolved_role = "Manager"
        
        # Look up employee profile to dynamically determine their role
        if emp_id and token:
            try:
                prof_res = httpx.get(
                    f"{get_settings().JAVA_BACKEND_URL}/api/employees/{emp_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=3.0
                )
                if prof_res.status_code == 200:
                    p_data = prof_res.json()
                    p_role = str(p_data.get("role", "")).lower()
                    if "finance" in p_role:
                        resolved_role = "Finance"
                    else:
                        resolved_role = "Manager"
            except Exception as e:
                logger.warning(f"Could not fetch profile for role resolution: {e}")
                
        query_params["role"] = resolved_role
        
        # Auto-inject approverId from user_context if not already set
        if "approverId" not in query_params:
            query_params["approverId"] = (body or {}).get("approverId") or user_context.get("employeeId", "")
            
        # Move comment/reason to query_params if rejecting
        if endpoint_id == "rejectClaim":
            r_reason = (body or {}).get("reason") or (body or {}).get("comment") or (query_params or {}).get("comment") or (query_params or {}).get("reason") or "Rejected by approver"
            query_params["reason"] = r_reason

        # Strip role/approverId/comment/reason from body so they don't get sent twice
        if body:
            body.pop("role", None)
            body.pop("approverId", None)
            body.pop("comment", None)
            body.pop("reason", None)
            # If nothing left in body (e.g. only id was there as path param), clear it
            remaining = {k: v for k, v in body.items() if k not in ("id", "claimId")}
            if not remaining:
                body = None

        # Check if actual_path ends with an invalid placeholder (e.g. <claim_id>, {id}, non-digit)
        import re
        id_match = re.search(r"/api/claims/(?:approve|reject)/([^/?#]+)", actual_path)
        extracted_id = id_match.group(1) if id_match else None
        
        if not extracted_id or not extracted_id.isdigit():
            # ID is missing or a placeholder string like "<claim_id>"
            # Try to auto-resolve from pending tasks
            all_tasks = WorkflowHelpers.build_my_tasks(user_context, token)
            claim_tasks = [t for t in all_tasks if "Claim" in str(t.get("Type", "")) and t.get("ID") is not None]
            
            if len(claim_tasks) == 1:
                resolved_id = str(claim_tasks[0]["ID"])
                logger.info(f"Auto-resolved claim ID {resolved_id} for {endpoint_id}")
                actual_path = re.sub(r"/api/claims/(approve|reject)/.*", f"/api/claims/\\1/{resolved_id}", actual_path)
            elif len(claim_tasks) > 1:
                task_list_str = ", ".join(f"ID {t.get('ID')} ({t.get('Employee', 'Unknown')} - {t.get('Details', '')})" for t in claim_tasks)
                return {
                    "status": "incomplete",
                    "error": f"There are multiple pending claims awaiting approval: {task_list_str}. Please specify the numeric ID of the claim you wish to act on.",
                    "endpoint_id": endpoint_id
                }
            else:
                return {
                    "status": "error",
                    "error": "No pending claims found awaiting approval.",
                    "endpoint_id": endpoint_id
                }

    # Special handling for Leave approve/reject: Java expects /api/leaves/action with specific body
    if endpoint_id in ("approveLeave", "rejectLeave", "takeAction"):
        body = body or {}
        # Map common field names to leaveRequestId
        for k in ["id", "leaveId", "taskId", "requestId"]:
            if k in body and "leaveRequestId" not in body:
                body["leaveRequestId"] = body.pop(k)
        if path_params and "id" in path_params and "leaveRequestId" not in body:
            body["leaveRequestId"] = path_params["id"]
            
        if "approverId" not in body:
            body["approverId"] = user_context.get("employeeId", "")
        if "role" not in body:
            body["role"] = "MANAGER"
        if "action" not in body:
            body["action"] = "Reject" if endpoint_id == "rejectLeave" else "Approve"
        if endpoint_id == "rejectLeave" and "remarks" not in body:
            body["remarks"] = body.get("reason") or body.get("comment") or "Rejected by manager"

        # Auto-resolve leaveRequestId if missing or non-digit
        cur_req_id = str(body.get("leaveRequestId", ""))
        if not cur_req_id or not cur_req_id.isdigit():
            all_tasks = WorkflowHelpers.build_my_tasks(user_context, token)
            leave_tasks = [t for t in all_tasks if "Leave" in str(t.get("Type", "")) and t.get("ID") is not None]
            if len(leave_tasks) == 1:
                body["leaveRequestId"] = leave_tasks[0]["ID"]
            elif len(leave_tasks) > 1:
                task_list_str = ", ".join(f"ID {t.get('ID')} ({t.get('Employee', 'Unknown')} - {t.get('Details', '')})" for t in leave_tasks)
                return {
                    "status": "incomplete",
                    "error": f"There are multiple pending leave requests awaiting approval: {task_list_str}. Please specify the numeric ID of the leave request.",
                    "endpoint_id": endpoint_id
                }

    # Special handling for Travel request approve/reject: Java expects PUT /api/travel/approve/{id}?managerId=...
    if endpoint_id in ("approveRequest", "rejectRequest", "approveTravelRequest", "rejectTravelRequest"):
        query_params = query_params or {}
        if "managerId" not in query_params:
            query_params["managerId"] = user_context.get("employeeId", "")
        if endpoint_id in ("rejectRequest", "rejectTravelRequest"):
            r_reason = (body or {}).get("rejectedReason") or (body or {}).get("reason") or (query_params or {}).get("reason") or (query_params or {}).get("rejectedReason") or "Rejected by manager due to budget limit"
            if len(r_reason) < 10:
                r_reason = f"Rejected: {r_reason} (exceeds budget limit)"
            query_params["rejectedReason"] = r_reason
            if body:
                body.pop("rejectedReason", None)
                body.pop("reason", None)

    # Special handling for creating Travel Ticket (POST /api/travel/create):
    if endpoint_id in ("createRequest", "createTravelRequest"):
        body = body or {}
        if "employeeId" not in body:
            body["employeeId"] = user_context.get("employeeId", "")
        if "name" not in body:
            body["name"] = user_context.get("name", "")
        if "departDate" in body and "departureDate" not in body:
            body["departureDate"] = body.pop("departDate")
        if "advanceRequired" in body:
            val = body["advanceRequired"]
            body["advanceRequired"] = True if str(val).lower() in ("yes", "true", "1") else False
        if "accommodationRequired" in body:
            val = body["accommodationRequired"]
            body["accommodationRequired"] = True if str(val).lower() in ("yes", "true", "1") else False

    # Automatically normalize any date fields from DD-MM-YYYY or DD/MM/YYYY to ISO YYYY-MM-DD
    if body and isinstance(body, dict):
        import re
        date_keys = [
            "departureDate", "departDate", "returnDate", "startDate", "endDate",
            "joiningDate", "dateOfBirth", "dob", "expenseDate", "claimDate", "date"
        ]
        for dk in date_keys:
            if dk in body and isinstance(body[dk], str):
                dm = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$", body[dk].strip())
                if dm:
                    d, mo, y = dm.group(1).zfill(2), dm.group(2).zfill(2), dm.group(3)
                    body[dk] = f"{y}-{mo}-{d}"



    # Special handling for Travel Admin booking document upload (POST /api/travel/admin/upload-pdfs/{requestId})
    if endpoint_id == "uploadMultipleFiles":
        path_params = path_params or {}
        body = body or {}
        for k in ["id", "travelRequestId", "ticketId", "requestId"]:
            if k in body and "requestId" not in path_params:
                path_params["requestId"] = str(body.pop(k))
            if k in path_params and "requestId" not in path_params:
                path_params["requestId"] = str(path_params[k])
                
        if "requestId" not in path_params or not str(path_params["requestId"]).isdigit():
            try:
                emp_id = user_context.get("employeeId", "")
                r_admin = httpx.get(
                    f"{get_settings().JAVA_BACKEND_URL}/api/travel/admin/assigned-requests/{emp_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=3.0
                )
                if r_admin.status_code == 200:
                    admin_tasks = r_admin.json()
                    if len(admin_tasks) == 1:
                        path_params["requestId"] = str(admin_tasks[0].get("id"))
            except Exception as e:
                logger.warning(f"Could not auto-resolve travel booking request ID: {e}")

        if "requestId" in path_params and "{requestId}" in actual_path:
            actual_path = actual_path.replace("{requestId}", str(path_params["requestId"]))
        body = None

    # Auto-resolve ticket and helpdesk path parameters
    if "{ticketId}" in actual_path:
        path_params = path_params or {}
        for k in ["ticketId", "id", "ticket_id"]:
            if k in path_params and "{ticketId}" in actual_path:
                actual_path = actual_path.replace("{ticketId}", str(path_params[k]))
            elif body and isinstance(body, dict) and k in body and "{ticketId}" in actual_path:
                actual_path = actual_path.replace("{ticketId}", str(body.pop(k)))
            elif query_params and isinstance(query_params, dict) and k in query_params and "{ticketId}" in actual_path:
                actual_path = actual_path.replace("{ticketId}", str(query_params.pop(k)))

    if "{employeeId}" in actual_path and endpoint_id in ("getMyTickets", "getDrafts", "getChangeRequestDrafts"):
        path_params = path_params or {}
        emp_id = path_params.get("employeeId") or user_context.get("employeeId", "scaloz_admin")
        actual_path = actual_path.replace("{employeeId}", str(emp_id))

    if "{managerId}" in actual_path and endpoint_id == "getTicketsForManager":
        path_params = path_params or {}
        mgr_id = path_params.get("managerId") or user_context.get("employeeId", "scaloz_admin")
        actual_path = actual_path.replace("{managerId}", str(mgr_id))

    # Auto-resolve employeeId for Compensation & Payroll endpoints
    if endpoint_id in ("getCompensationDetails", "getCompensationHistory", "getPayslipsByEmployee"):
        path_params = path_params or {}
        if "employeeId" not in path_params or not path_params["employeeId"]:
            path_params["employeeId"] = user_context.get("employeeId", "scaloz_admin")
        if "{employeeId}" in actual_path:
            actual_path = actual_path.replace("{employeeId}", str(path_params["employeeId"]))

    MONTH_NAME_MAP = {
        "1": "January", "01": "January", "jan": "January", "january": "January",
        "2": "February", "02": "February", "feb": "February", "february": "February",
        "3": "March", "03": "March", "mar": "March", "march": "March",
        "4": "April", "04": "April", "apr": "April", "april": "April",
        "5": "May", "05": "May", "may": "May",
        "6": "June", "06": "June", "jun": "June", "june": "June",
        "7": "July", "07": "July", "jul": "July", "july": "July",
        "8": "August", "08": "August", "aug": "August", "august": "August",
        "9": "September", "09": "September", "sep": "September", "september": "September",
        "10": "October", "oct": "October", "october": "October",
        "11": "November", "nov": "November", "november": "November",
        "12": "December", "dec": "December", "december": "December"
    }

    if endpoint_id in ("getPayslipByMonthAndYear", "getPayslipsByMonthYear"):
        path_params = path_params or {}
        # Auto-map from body/query_params if LLM passed them there
        if body and isinstance(body, dict):
            if "month" in body and "month" not in path_params:
                path_params["month"] = body["month"]
            if "year" in body and "year" not in path_params:
                path_params["year"] = body["year"]
        if query_params and isinstance(query_params, dict):
            if "month" in query_params and "month" not in path_params:
                path_params["month"] = query_params["month"]
            if "year" in query_params and "year" not in path_params:
                path_params["year"] = query_params["year"]
        if "month" in path_params:
            m_val = str(path_params["month"]).strip().lower()
            if m_val in MONTH_NAME_MAP:
                path_params["month"] = MONTH_NAME_MAP[m_val]
        if "month" in path_params and "{month}" in actual_path:
            actual_path = actual_path.replace("{month}", str(path_params["month"]))
        if "year" in path_params and "{year}" in actual_path:
            actual_path = actual_path.replace("{year}", str(path_params["year"]))

    if endpoint_id == "generatePayslips" and body and isinstance(body, dict) and "month" in body:
        m_val = str(body["month"]).strip().lower()
        if m_val in MONTH_NAME_MAP:
            body["month"] = MONTH_NAME_MAP[m_val]

    # Special handling for sendOnboardingEmail: auto-fetch applicant details if missing
    if endpoint_id == "sendOnboardingEmail":
        body = body or {}
        if "applicantId" not in body and path_params and "applicantId" in path_params:
            body["applicantId"] = path_params["applicantId"]
        
        target_app_id = body.get("applicantId")
        if not target_app_id:
            try:
                apps_res = httpx.get(
                    f"{get_settings().JAVA_BACKEND_URL}/api/v1/applicants",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=3.0
                )
                if apps_res.status_code == 200:
                    apps_list = apps_res.json()
                    if len(apps_list) == 1:
                        target_app_id = apps_list[0].get("applicantId")
                        body["applicantId"] = target_app_id
            except Exception as e:
                logger.warning(f"Could not auto-resolve applicant: {e}")

        # Fetch full applicant details to fill firstName, lastName, email
        if target_app_id and token:
            try:
                app_res = httpx.get(
                    f"{get_settings().JAVA_BACKEND_URL}/api/v1/applicants/{target_app_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=3.0
                )
                if app_res.status_code == 200:
                    app_data = app_res.json()
                    if "firstName" not in body or not body["firstName"]:
                        body["firstName"] = app_data.get("firstName", "")
                    if "lastName" not in body or not body["lastName"]:
                        body["lastName"] = app_data.get("lastName", "")
                    if "email" not in body or not body["email"]:
                        body["email"] = app_data.get("email", "")
            except Exception as e:
                logger.warning(f"Could not fetch applicant details for onboarding email: {e}")

    # Normalize ticket and grievance field aliases
    if endpoint_id in ("submitTicket", "saveDraftTicket", "saveDraft", "submitChangeRequest", "saveChangeRequestDraft") and body and isinstance(body, dict):
        if "title" in body and "issueSummary" not in body:
            body["issueSummary"] = body["title"]
        if "issueSummary" in body and "title" not in body:
            body["title"] = body["issueSummary"]
        if "description" in body and "detailedDescription" not in body:
            body["detailedDescription"] = body["description"]
        if "detailedDescription" in body and "description" not in body:
            body["description"] = body["detailedDescription"]
        if "subCategory" in body and "subcategory" not in body:
            body["subcategory"] = body["subCategory"]
        if "subcategory" in body and "subCategory" not in body:
            body["subCategory"] = body["subcategory"]
        if "changeDescription" in body and "detailedDescription" not in body:
            body["detailedDescription"] = body["changeDescription"]
        if "justification" in body and "issueSummary" not in body:
            body["issueSummary"] = body["justification"]
        if "issueSummary" in body and "justification" not in body:
            body["justification"] = body["issueSummary"]
        if "detailedDescription" in body and "changeDescription" not in body:
            body["changeDescription"] = body["detailedDescription"]

    if endpoint_id in ("submitGrievance",) and body and isinstance(body, dict):
        if "title" in body and "subject" not in body:
            body["subject"] = body["title"]
        if "detailedDescription" in body and "description" not in body:
            body["description"] = body["detailedDescription"]

    # Special handling for Customer operations
    def _normalize_customer_iso_date(dt_str: str) -> str:
        if not dt_str:
            return dt_str
        try:
            s = str(dt_str).strip()
            if "-" in s and len(s.split("-")[0]) == 2:
                parts = s.split("-")
                return f"{parts[2]}-{parts[1]}-{parts[0]}"
            if "/" in s:
                parts = s.split("/")
                if len(parts[0]) == 2:
                    return f"{parts[2]}-{parts[1]}-{parts[0]}"
                return f"{parts[0]}-{parts[1]}-{parts[2]}"
        except Exception:
            pass
        return str(dt_str).strip()

    if endpoint_id in ("createCustomer", "updateCustomer") and body and isinstance(body, dict):
        if "name" in body and "customerName" not in body:
            body["customerName"] = body.pop("name")
        if "clientName" in body and "customerName" not in body:
            body["customerName"] = body.pop("clientName")
        if "msaStartDate" in body and "startDate" not in body:
            body["startDate"] = body.pop("msaStartDate")
        if "msaEndDate" in body and "endDate" not in body:
            body["endDate"] = body.pop("msaEndDate")
        if "startDate" in body:
            body["startDate"] = _normalize_customer_iso_date(body["startDate"])
        if "endDate" in body:
            body["endDate"] = _normalize_customer_iso_date(body["endDate"])

    if endpoint_id == "updateCustomer" and body and isinstance(body, dict):
        cust_id = None
        if path_params and "id" in path_params:
            cust_id = str(path_params["id"]).replace("cid", "").replace("CID", "").strip()
            path_params["id"] = cust_id
        elif "id" in body:
            cust_id = str(body["id"]).replace("cid", "").replace("CID", "").strip()
            body["id"] = cust_id
            
        if cust_id and "{id}" in actual_path:
            actual_path = actual_path.replace("{id}", str(cust_id))
            
        if "name" in body and "customerName" not in body:
            body["customerName"] = body.pop("name")
        if "clientName" in body and "customerName" not in body:
            body["customerName"] = body.pop("clientName")

        if cust_id and token:
            try:
                settings = get_settings()
                r_cust = httpx.get(
                    f"{settings.JAVA_BACKEND_URL}/api/customers/{cust_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=3.0
                )
                if r_cust.status_code == 200:
                    cdata = r_cust.json()
                    if "customerName" not in body or not body["customerName"]:
                        body["customerName"] = cdata.get("customerName", "")
                    if "startDate" not in body or not body["startDate"]:
                        body["startDate"] = str(cdata.get("startDate", ""))
                    if "endDate" not in body or not body["endDate"]:
                        body["endDate"] = str(cdata.get("endDate", ""))
            except Exception as e:
                logger.warning(f"Could not auto-populate customer details: {e}")

    if body and endpoint_id not in ("submitEntry", "updateEntry", "applyLeave"): # These fields will be auto-injected
        missing = [f for f in required_fields if f not in body]
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

    if endpoint_id == "markAllNotificationsAsRead":
        emp_id = user_context.get("employeeId", "")
        settings = get_settings()
        h = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r_notifs = await client.get(f"{settings.JAVA_BACKEND_URL}/api/notifications/{emp_id}", headers=h)
                if r_notifs.status_code == 200:
                    notifs = r_notifs.json()
                    if isinstance(notifs, list):
                        unread_notifs = [n for n in notifs if not n.get("read")]
                        if not unread_notifs:
                            return {"message": "All notifications are already marked as read."}
                        import asyncio
                        tasks = [
                            client.post(f"{settings.JAVA_BACKEND_URL}/api/notifications/read/{n['id']}", headers=h)
                            for n in unread_notifs if "id" in n
                        ]
                        await asyncio.gather(*tasks, return_exceptions=True)
                        return {"message": f"Successfully marked {len(unread_notifs)} notification(s) as read."}
            return {"message": "All notifications processed."}
        except Exception as e:
            logger.error(f"Error marking all notifications as read: {e}")
            return {"status": "error", "error": str(e)}

    # Auto-map conversational field names from LLM to strict Java entity fields
    if endpoint_id == "updateProfile" and body:
        mapping = {
            "contactNumber": "contactNo",
            "phone": "contactNo",
            "emergencyNumber": "emergencyContactNumber",
            "emergencyContact": "emergencyContactNumber",
            "emergencyNo": "emergencyContactNumber",
            "emergency": "emergencyContactNumber",
            "emg": "emergencyContactNumber",
            "personalEmail": "personalMail",
            "personalMailId": "personalMail",
            "permanentAddress": "address",
            "presentAddress": "presentAddress",
            "bio": "about",
            "myInterestsAndHobbies": "interestsAndHobbies",
            "hobbies": "interestsAndHobbies"
        }
        for bad_key, good_key in mapping.items():
            if bad_key in body and good_key not in body:
                body[good_key] = body.pop(bad_key)
                
    if endpoint_id in ("submitClaim", "saveClaim", "addNominee") and body:
        mapping = {
            "date": "expenseDate",
            "description": "expenseDescription",
            "type": "category",
            "claimType": "category",
            "dateOfBirth": "dateOfBirth", # Ensures correct casing if it hallucinated dateofbirth
            "dob": "dateOfBirth"
        }
        # Add nominee mappings specifically
        if endpoint_id == "addNominee":
            mapping.update({
                "name": "nomineeName"
            })
            
        for bad_key, good_key in mapping.items():
            # Support case insensitive bad_key matches if needed, but exact is fine for LLM hallucinations
            if bad_key in body and good_key not in body:
                body[good_key] = body.pop(bad_key)

    if endpoint_id == "submitResignation" and body:
        if "reason" in body and "reasonForExit" not in body:
            body["reasonForExit"] = body.pop("reason")
        if "exitReason" in body and "reasonForExit" not in body:
            body["reasonForExit"] = body.pop("exitReason")
        if "proposedLastWorkingDay" in body and "lastWorkingDay" not in body:
            body["lastWorkingDay"] = body.pop("proposedLastWorkingDay")
        if "lwd" in body and "lastWorkingDay" not in body:
            body["lastWorkingDay"] = body.pop("lwd")
        if "resignationDate" not in body:
            from datetime import datetime
            body["resignationDate"] = datetime.now().strftime("%d-%m-%Y")

    if endpoint_id == "createAsset" and body:
        import time

        async def _prepare_single_asset(b: dict):
            import random
            ts = int(time.time() * 1000)
            rnd = random.randint(100, 999)
            raw_tag = b.get("assetTag")
            if not raw_tag:
                b["assetTag"] = f"AST-{ts}-{rnd}"
            elif not raw_tag.startswith("AST-"):
                b["assetTag"] = f"AST-{raw_tag}-{rnd}"
                
            if "status" not in b:
                b["status"] = "IN_STOCK"
            if "conditionAtStock" not in b:
                b["conditionAtStock"] = "NEW"
                
            cat_val = b.get("categoryId") or b.get("category") or ""
            subcat_val = b.get("subCategoryId") or b.get("subCategory") or ""
            cat_name = str(cat_val).title() if cat_val else ""
            subcat_name = str(subcat_val).title() if subcat_val else ""
            
            try:
                settings = get_settings()
                h = {"Authorization": f"Bearer {token}"} if token else {}
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r_cats = await client.get(f"{settings.JAVA_BACKEND_URL}/api/assets/categories", headers=h)
                    if r_cats.status_code == 200:
                        categories = r_cats.json()
                        cat_str = str(cat_val).strip()
                        matched_cat = None
                        
                        # Match by ID or Name
                        if isinstance(cat_val, int) or (isinstance(cat_val, str) and cat_val.isdigit()):
                            c_id = int(cat_val)
                            for c in categories:
                                if c.get("id") == c_id:
                                    matched_cat = c
                                    break
                        
                        if not matched_cat and cat_str:
                            for c in categories:
                                if c.get("name", "").lower() == cat_str.lower() or c.get("name", "").lower() in cat_str.lower() or cat_str.lower() in c.get("name", "").lower():
                                    matched_cat = c
                                    break
                        
                        if not matched_cat and cat_str and not cat_str.isdigit():
                            # Auto-create parent category in Java
                            r_new_cat = await client.post(f"{settings.JAVA_BACKEND_URL}/api/assets/categories", headers=h, json={"name": cat_str.title(), "active": True})
                            if r_new_cat.status_code in (200, 201):
                                matched_cat = r_new_cat.json()
                                matched_cat["subCategories"] = []
                                
                        if matched_cat:
                            b["categoryId"] = matched_cat["id"]
                            cat_name = matched_cat.get("name", cat_str).title()
                            
                            # Resolve or create subcategory
                            sub_list = matched_cat.get("subCategories") or []
                            sub_target = str(subcat_val or (cat_name + "s" if not cat_name.endswith("s") else cat_name)).strip()
                            matched_sub = None
                            
                            if isinstance(subcat_val, int) or (isinstance(subcat_val, str) and subcat_val.isdigit()):
                                s_id = int(subcat_val)
                                for s in sub_list:
                                    if s.get("id") == s_id:
                                        matched_sub = s
                                        break
                                        
                            if not matched_sub and sub_target:
                                for s in sub_list:
                                    if s.get("name", "").lower() == sub_target.lower() or s.get("name", "").lower() in sub_target.lower():
                                        matched_sub = s
                                        break
                            
                            if matched_sub:
                                b["subCategoryId"] = matched_sub["id"]
                                subcat_name = matched_sub.get("name", sub_target).title()
                            elif sub_list and not subcat_val:
                                b["subCategoryId"] = sub_list[0]["id"]
                                subcat_name = sub_list[0].get("name", sub_target).title()
                            else:
                                # Auto-create subcategory in Java backend attached to parentCategory
                                try:
                                    r_new_sub = await client.post(
                                        f"{settings.JAVA_BACKEND_URL}/api/assets/categories",
                                        headers=h,
                                        json={"name": sub_target.title(), "active": True, "fieldConfigs": [], "parentCategory": {"id": matched_cat["id"]}}
                                    )
                                    if r_new_sub.status_code in (200, 201):
                                        new_sub_obj = r_new_sub.json()
                                        b["subCategoryId"] = new_sub_obj.get("id")
                                        subcat_name = new_sub_obj.get("name", sub_target).title()
                                except Exception as e_sub:
                                    logger.warning(f"Failed to auto-create subcategory: {e_sub}")
            except Exception as e:
                logger.warning(f"Failed to auto-resolve asset category: {e}")

            if not cat_name and b.get("categoryId"):
                cat_name = f"Category-{b['categoryId']}"
            if not subcat_name and b.get("subCategoryId"):
                subcat_name = f"Subcategory-{b['subCategoryId']}"

            if "dynamicValues" not in b or not b["dynamicValues"]:
                b["dynamicValues"] = {
                    "Category": cat_name,
                    "Sub-category": subcat_name,
                    "Asset Tag": b["assetTag"]
                }
            else:
                b["dynamicValues"]["Asset Tag"] = b["assetTag"]
                if cat_name:
                    b["dynamicValues"]["Category"] = cat_name
                if subcat_name:
                    b["dynamicValues"]["Sub-category"] = subcat_name

            # Remove string category / subCategory so Jackson doesn't fail on Map<String, Object>
            b.pop("category", None)
            b.pop("subCategory", None)

        if isinstance(body, list):
            for item in body:
                if isinstance(item, dict):
                    await _prepare_single_asset(item)
        elif isinstance(body, dict):
            if "assets" in body and isinstance(body["assets"], list):
                for item in body["assets"]:
                    if isinstance(item, dict):
                        await _prepare_single_asset(item)
            else:
                await _prepare_single_asset(body)

    if endpoint_id == "allocateAsset" and body:
        if "assetId" in body and "asset" not in body:
            body["asset"] = {"id": body.pop("assetId")}
        elif isinstance(body.get("asset"), (int, str)):
            body["asset"] = {"id": body["asset"]}
        if "employeeId" in body and "employee" not in body:
            body["employee"] = {"employeeId": body.pop("employeeId")}
        elif isinstance(body.get("employee"), str):
            body["employee"] = {"employeeId": body["employee"]}

    if endpoint_id in ("submitTicket", "submitChangeRequest", "saveDraftTicket", "saveDraft", "saveChangeRequestDraft") and body:
        if isinstance(body, dict):
            caller_emp = user_context.get("employeeId") or user_context.get("userId") or "scaloz_admin"
            if "employeeId" not in body and caller_emp:
                body["employeeId"] = caller_emp
            if "ccToManager" not in body:
                body["ccToManager"] = False

    # Auto-resolve category for claims: fetch categories from Java and map name -> ID
    if endpoint_id in ("submitClaim", "saveClaim", "saveDraftClaim") and body:
        if "categoryId" in body and "category" not in body:
            body["category"] = body.pop("categoryId")

        category_val = body.get("category")
        needs_resolution = category_val is None or isinstance(category_val, str)
        
        KNOWN_CATEGORIES = {
            "travel": 1,
            "accommodation": 2,
            "food": 3,
            "fuel": 4,
            "others": 5,
            "other": 5,
            "misc": 5,
            "miscellaneous": 5,
            "office supplies": 5,
            "gifts": 5,
            "team gifts": 5
        }
        
        if needs_resolution:
            resolved_id = None
            if category_val and isinstance(category_val, str):
                resolved_id = KNOWN_CATEGORIES.get(category_val.strip().lower())
            
            # Infer from fields if still None
            if not resolved_id:
                if body.get("subCategory") or body.get("justification"):
                    resolved_id = 5 # Others
                elif body.get("fromLocation") or body.get("toLocation") or body.get("mode") or body.get("tripCategory"):
                    resolved_id = 1 # Travel
                elif body.get("hotelName") or body.get("city") or body.get("checkInDate"):
                    resolved_id = 2 # Accommodation
                elif body.get("mealType") or body.get("numberOfPeople"):
                    resolved_id = 3 # Food
                elif body.get("vehicle") or body.get("distanceKm"):
                    resolved_id = 4 # Fuel
                    
            if resolved_id:
                body["category"] = resolved_id
            else:
                try:
                    settings = get_settings()
                    cat_url = f"{settings.JAVA_BACKEND_URL}/api/claims/categories"
                    headers = {}
                    if token:
                        headers["Authorization"] = f"Bearer {token}"
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        cat_resp = await client.get(cat_url, headers=headers)
                        if cat_resp.status_code == 200:
                            categories = cat_resp.json()
                            if isinstance(categories, list) and len(categories) > 0:
                                if category_val and isinstance(category_val, str):
                                    cat_lower = category_val.lower()
                                    for cat in categories:
                                        cat_name = (cat.get("name") or cat.get("categoryName") or "").lower()
                                        if cat_name == cat_lower or cat_lower in cat_name or cat_name in cat_lower:
                                            body["category"] = cat.get("id") or cat.get("categoryId")
                                            break
                                if "category" not in body or body.get("category") is None:
                                    body["category"] = categories[0].get("id") or categories[0].get("categoryId")
                except Exception as e:
                    logger.warning(f"Failed to auto-resolve category from Java: {e}")
                    if "category" not in body or body.get("category") is None:
                        body["category"] = 5
                # Don't block submission - the required_fields check will catch it if still missing

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
                    body.get("type", body.get("leaveTypeId", "")),
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
        
        if actual_path.startswith("/api/assets"):
            if not query_params:
                query_params = {}
            if "userId" not in query_params:
                query_params["userId"] = user_context.get("employeeId", "scaloz_admin")

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
            if user_context.get("temp_file_path"):
                action_data["temp_file_path"] = user_context.get("temp_file_path")
            else:
                import os
                upload_dir = "/tmp/xevyte_uploads"
                if os.path.exists(upload_dir):
                    filename = (body or {}).get("receiptFile")
                    matches = []
                    for f in os.listdir(upload_dir):
                        if not filename or f.endswith("_" + filename) or f == filename:
                            matches.append(os.path.join(upload_dir, f))
                    if matches:
                        matches.sort(key=os.path.getmtime, reverse=True)
                        action_data["temp_file_path"] = matches[0]
            emp_id = user_context.get("employeeId", "unknown")
            confirm_token = generate_confirmation_token(action_data, emp_id)
            
            return {
                "status": "pending_confirmation",
                "message": "SYSTEM DIRECTIVE: The API call is prepared. STOP EXECUTION IMMEDIATELY. DO NOT call any other tools. DO NOT retry. Respond ONLY with a summary of the action and tell the user 'Please click the Approve button below to confirm.'",
                "pending_confirmation_token": confirm_token,
                "summary": f"Ready to execute {method} on {actual_path}",
                "action_data": action_data,
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
        
    if actual_path.startswith("/api/v1/exit-management/") or actual_path.startswith("/api/v1/exit-forms"):
        emp_id = user_context.get("employeeId", "")
        emp_name = user_context.get("name") or user_context.get("employeeName") or emp_id
        mgr_id = user_context.get("reportingManager") or user_context.get("managerId") or emp_id
        mgr_name = user_context.get("managerName") or emp_name
        dept = user_context.get("department") or "Admin"
        
        headers["employeeId"] = emp_id
        headers["employeeName"] = emp_name
        headers["managerId"] = mgr_id
        headers["managerName"] = mgr_name
        headers["department"] = dept
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            request_kwargs = {
                "url": url,
                "headers": headers,
            }
            
            if query_params:
                request_kwargs["params"] = query_params
            
            if query_params:
                request_kwargs["params"] = query_params
            
            if body and method != "GET":
                if endpoint_id == "updateProfilePicture":
                    # Multipart file upload handling for profile picture
                    if "Content-Type" in headers:
                        del headers["Content-Type"]
                    data = {}
                    files = {}
                    import os
                    for k, v in body.items():
                        if k == "profilePic" and isinstance(v, str) and os.path.isfile(v):
                            files["profilePic"] = open(v, "rb")
                        else:
                            data[k] = str(v)
                    
                    # Ensure firstName and lastName are present (required by backend)
                    if "firstName" not in data:
                        data["firstName"] = "User"
                    if "lastName" not in data:
                        data["lastName"] = ""
                        
                    request_kwargs["data"] = data
                    if files:
                        request_kwargs["files"] = files
                
                elif endpoint_id in ("submitClaim", "saveDraft", "saveClaim"):
                    # Multipart file upload handling for claims
                    if "Content-Type" in headers:
                        del headers["Content-Type"]
                    
                    # The Java backend expects the JSON data as a stringified 'claim' part
                    claim_data = body.copy()
                    receipt_path = claim_data.pop("receiptFile", None)
                    
                    data = {"claim": json.dumps(claim_data)}
                    files = {}
                    import os
                    if receipt_path and isinstance(receipt_path, str) and os.path.isfile(receipt_path):
                        files["receiptFile"] = open(receipt_path, "rb")
                        
                    request_kwargs["data"] = data
                    if files:
                        request_kwargs["files"] = files
                else:
                    request_kwargs["json"] = body
            
            response = await client.request(method, **request_kwargs)
            
            # ================================================================
            # STEP 6: Parse response
            # ================================================================
            
            try:
                resp_data = response.json()
            except Exception:
                content_type = response.headers.get("content-type", "")
                if "octet-stream" in content_type or "pdf" in content_type or "image" in content_type:
                    cd = response.headers.get("content-disposition", "")
                    filename = "document.pdf"
                    if "filename=" in cd:
                        filename = cd.split("filename=")[-1].strip('"').strip("'")
                    
                    import os, uuid
                    unique_filename = f"{uuid.uuid4().hex[:8]}_{filename}"
                    os.makedirs("downloads", exist_ok=True)
                    with open(os.path.join("downloads", unique_filename), "wb") as f:
                        f.write(response.content)

                    resp_data = {
                        "message": f"Successfully retrieved document '{filename}' ({len(response.content)} bytes).",
                        "filename": filename,
                        "sizeBytes": len(response.content),
                        "downloadUrl": f"http://localhost:8000/downloads/{unique_filename}"
                    }
                else:
                    resp_data = response.text
            
            # Success response
            if response.status_code in (200, 201, 204):
                
                # Map Java backend keys to expected Python keys without hardcoded null sanitization
                if endpoint_id == "getAllocationsForEmployee" and isinstance(resp_data, list):
                    for alloc in resp_data:
                        if "customerName" in alloc:
                            alloc["clientName"] = alloc.get("customerName")
                            
                if endpoint_id in ("getProfile", "getEmployeeOverview") and isinstance(resp_data, dict):
                    if "designation" in resp_data:
                        resp_data["role"] = resp_data.get("designation")
                    if "assignedManagerId" in resp_data:
                        resp_data["reportingManager"] = resp_data.get("assignedManagerId")
                    elif "managerName" in resp_data:
                        resp_data["reportingManager"] = resp_data.get("managerName")

                # ----------------------------------------------------------
                # Strip binary blob fields from Customer responses.
                # The Java backend returns the full msaDocBlob (base64 LONGBLOB)
                # in getAllCustomers / getCustomerById / getCustomersForEmployee.
                # Passing that to the LLM causes it to dump raw base64 in the
                # chat.  Replace with a clean downloadUrl for the user.
                # ----------------------------------------------------------
                def _sanitize_customer(cust_dict):
                    """Remove msaDocBlob and add downloadUrl."""
                    if not isinstance(cust_dict, dict):
                        return cust_dict
                    cust_dict.pop("msaDocBlob", None)
                    cid = cust_dict.get("customerId") or cust_dict.get("id") or cust_dict.get("tenantCustomerId")
                    if cid:
                        cust_dict["msaDownloadUrl"] = f"http://localhost:8082/api/customers/{cid}/download"
                    return cust_dict

                if endpoint_id in ("getAllCustomers", "getCustomerById", "getCustomersForEmployee"):
                    if isinstance(resp_data, list):
                        resp_data = [_sanitize_customer(c) for c in resp_data]
                    elif isinstance(resp_data, dict):
                        resp_data = _sanitize_customer(resp_data)

                # ----------------------------------------------------------
                # Strip binary blob fields from SOW responses.
                # Same pattern as customers: sowDocBlob → sowDownloadUrl.
                # ----------------------------------------------------------
                def _sanitize_sow(sow_dict):
                    """Remove sowDocBlob and add downloadUrl."""
                    if not isinstance(sow_dict, dict):
                        return sow_dict
                    sow_dict.pop("sowDocBlob", None)
                    sow_dict.pop("sowDoc", None)
                    sid = sow_dict.get("sowId") or sow_dict.get("id")
                    if sid:
                        sow_dict["sowDownloadUrl"] = f"http://localhost:8082/api/sows/{sid}/download"
                    return sow_dict

                if endpoint_id in ("getSowsByCustomer", "getAllSows", "getSowById", "createSow"):
                    if isinstance(resp_data, list):
                        resp_data = [_sanitize_sow(s) for s in resp_data]
                    elif isinstance(resp_data, dict):
                        resp_data = _sanitize_sow(resp_data)
                        
                # ----------------------------------------------------------
                # Strip binary base64 from Payslip JSON responses
                # ----------------------------------------------------------
                def _sanitize_payslip(payslip_dict):
                    if not isinstance(payslip_dict, dict):
                        return payslip_dict
                    pdf_b64 = payslip_dict.pop("payslipPdf", None)
                    pid = payslip_dict.get("id")
                    pdf_name = payslip_dict.get("payslipPdfName", f"payslip_{pid}.pdf") if payslip_dict.get("payslipPdfName") else f"payslip_{pid}.pdf"
                    if pdf_b64:
                        import base64, os, uuid
                        try:
                            pdf_bytes = base64.b64decode(pdf_b64)
                            unique_filename = f"{uuid.uuid4().hex[:8]}_{pdf_name}"
                            os.makedirs("downloads", exist_ok=True)
                            with open(os.path.join("downloads", unique_filename), "wb") as f:
                                f.write(pdf_bytes)
                            payslip_dict["payslipDownloadUrl"] = f"http://localhost:8000/downloads/{unique_filename}"
                        except Exception as e:
                            payslip_dict["payslipDownloadUrl"] = "Error decoding PDF"
                    return payslip_dict

                if endpoint_id in ("getPayslipsByMonthYear", "generatePayslipsForAll", "getPayslipsByEmployee"):
                    if isinstance(resp_data, dict) and "payslips" in resp_data:
                        resp_data["payslips"] = [_sanitize_payslip(p) for p in resp_data["payslips"]]
                    elif isinstance(resp_data, list):
                        resp_data = [_sanitize_payslip(p) for p in resp_data]
                    elif isinstance(resp_data, dict):
                        resp_data = _sanitize_payslip(resp_data)
                
                return {
                    "status": "success",
                    "status_code": response.status_code,
                    "data": resp_data
                }
            
            # Error response
            else:
                if isinstance(resp_data, dict):
                    error_msg = resp_data.get("error") or resp_data.get("message") or resp_data.get("detail") or str(resp_data)
                else:
                    error_msg = str(resp_data)
                
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
                    if "pending" in str(l.get("status", "")).lower():
                        emp_name = l.get("employeeName")
                        if not emp_name or str(emp_name).strip().lower() in ("null null", "null", "none", "unknown", ""):
                            emp_name = l.get("employeeId") or "Unknown Employee"

                        leave_type = l.get("type") or l.get("leaveType")
                        if not leave_type or str(leave_type).strip().lower() in ("none", "null", ""):
                            leave_type = "Leave"

                        ref_id = l.get("referenceId") or l.get("leaveReference") or "N/A"
                        start_d = l.get("startDate") or "N/A"
                        end_d = l.get("endDate") or "N/A"
                        days = l.get("totalDays")
                        days_str = f" ({days} day{'s' if days and days > 1 else ''})" if days else ""

                        tasks.append({
                            "ID": l.get("id"),
                            "Reference ID": ref_id,
                            "Type": "Leave Approval",
                            "Leave Type": leave_type,
                            "Employee": emp_name,
                            "Details": f"{leave_type}{days_str} from {start_d} to {end_d}",
                            "Date": l.get("createdAt", "N/A")
                        })
            
            # 2. Claims
            r_claims = httpx.get(f"{get_settings().JAVA_BACKEND_URL}/api/claims/manager/{emp_id}", headers=headers, timeout=5.0)
            if r_claims.status_code == 200:
                for c in r_claims.json():
                    if "pending" in str(c.get("status", "")).lower():
                        emp_name = c.get("employeeName")
                        if not emp_name or str(emp_name).strip().lower() in ("null null", "null", "none", "unknown", ""):
                            emp_name = c.get("employeeId") or "Unknown Employee"

                        exp_type = c.get("expenseType") or "Claim"
                        amt = c.get("amount") or "0"
                        ref_id = c.get("claimGroupId") or c.get("referenceId") or "N/A"

                        tasks.append({
                            "ID": c.get("id"),
                            "Reference ID": ref_id,
                            "Type": "Claim Approval",
                            "Leave Type": exp_type,
                            "Employee": emp_name,
                            "Details": f"{exp_type} - {amt}",
                            "Date": c.get("appliedOn", "N/A")
                        })
            
            # 3. Travel (Manager Pending + Admin Assigned)
            r_travel = httpx.get(f"{get_settings().JAVA_BACKEND_URL}/api/travel/manager/pending/{emp_id}", headers=headers, timeout=5.0)
            if r_travel.status_code == 200:
                for t in r_travel.json():
                    emp_name = t.get("employeeName")
                    if not emp_name or str(emp_name).strip().lower() in ("null null", "null", "none", "unknown", ""):
                        emp_name = t.get("employeeId") or "Unknown Employee"

                    purpose = t.get("purposeOfTravel") or t.get("purpose") or "Travel"
                    from_loc = t.get("fromLocation") or "N/A"
                    to_loc = t.get("toLocation") or t.get("destination") or "N/A"
                    mode = t.get("modeOfTravel") or "Trip"
                    ref_id = t.get("referenceId") or "N/A"

                    tasks.append({
                        "ID": t.get("id"),
                        "Reference ID": ref_id,
                        "Type": "Travel Approval",
                        "Leave Type": purpose,
                        "Employee": emp_name,
                        "Details": f"{mode} ({from_loc} -> {to_loc}) - {purpose}",
                        "Date": t.get("createdAt", t.get("requestDate", "N/A"))
                    })

            # 3b. Travel Admin Assigned (Pending booking/completion)
            try:
                r_travel_admin = httpx.get(f"{get_settings().JAVA_BACKEND_URL}/api/travel/admin/assigned-requests/{emp_id}", headers=headers, timeout=5.0)
                if r_travel_admin.status_code == 200:
                    for t in r_travel_admin.json():
                        if t.get("status") in ("Approved By Manager", "Pending For Booking", "In Progress"):
                            emp_name = t.get("employeeName")
                            if not emp_name or str(emp_name).strip().lower() in ("null null", "null", "none", "unknown", ""):
                                emp_name = t.get("employeeId") or "Unknown Employee"

                            purpose = t.get("purposeOfTravel") or t.get("purpose") or "Travel Booking"
                            from_loc = t.get("fromLocation") or "N/A"
                            to_loc = t.get("toLocation") or t.get("destination") or "N/A"
                            mode = t.get("modeOfTravel") or "Trip"

                            tasks.append({
                                "ID": t.get("id"),
                                "Reference ID": t.get("referenceId") or f"TRV-{t.get('id')}",
                                "Type": "Travel Admin Booking",
                                "Leave Type": purpose,
                                "Employee": emp_name,
                                "Details": f"{mode} ({from_loc} -> {to_loc}) [Ready for Booking Upload]",
                                "Date": t.get("createdAt", "N/A")
                            })
            except Exception as e:
                logger.warning(f"Could not fetch travel admin tasks: {e}")
            
            # 5. Exit/Resignation Tasks
            try:
                headers_exit = dict(headers)
                headers_exit["managerId"] = emp_id
                headers_exit["employeeId"] = emp_id
                r_exits = httpx.get(f"{get_settings().JAVA_BACKEND_URL}/api/v1/exit-management/manager/pending-resignations", headers=headers_exit, timeout=5.0)
                if r_exits.status_code == 200:
                    for ex in r_exits.json():
                        if ex.get("status") != "Final Approved - Exit Complete":
                            emp_name = ex.get("employeeName")
                            if not emp_name or str(emp_name).strip().lower() in ("null null", "null", "none", "unknown", ""):
                                emp_name = ex.get("employeeId") or "Unknown Employee"

                            ref_id = ex.get("referenceId") or "N/A"

                            tasks.append({
                                "ID": ex.get("id"),
                                "Reference ID": ref_id,
                                "Type": "Exit/Resignation Approval",
                                "Leave Type": "Resignation",
                                "Employee": emp_name,
                                "Details": f"Resignation Date: {ex.get('resignationDate', 'N/A')}",
                                "Date": ex.get("createdDate", "N/A")
                            })
            except Exception as e:
                logger.warning(f"Could not fetch exit tasks: {e}")

            # 4. Tickets
            r_tickets = httpx.get(f"{get_settings().JAVA_BACKEND_URL}/api/tickets/manager/{emp_id}", headers=headers, timeout=5.0)
            if r_tickets.status_code == 200:
                for tk in r_tickets.json():
                    if "pending" in str(tk.get("status", "")).lower() or "open" in str(tk.get("status", "")).lower():
                        emp_name = tk.get("employeeName")
                        if not emp_name or str(emp_name).strip().lower() in ("null null", "null", "none", "unknown", ""):
                            emp_name = tk.get("employeeId") or "Unknown Employee"

                        details = tk.get("title") or tk.get("subject") or "Helpdesk Ticket"
                        ref_id = tk.get("ticketNumber") or tk.get("referenceId") or "N/A"

                        tasks.append({
                            "ID": tk.get("id"),
                            "Reference ID": ref_id,
                            "Type": "Ticket Approval",
                            "Leave Type": tk.get("category", "Helpdesk"),
                            "Employee": emp_name,
                            "Details": details,
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
        balances = balance_result.get("data", [])
        if isinstance(balances, dict):
            balances = balances.get("leaveBalances", balances.get("balances", []))
            
        leave_type_balance = next(
            (b for b in balances if str(b.get("type", b.get("leaveType", ""))).strip().lower() == str(leave_type_id).strip().lower()),
            None
        )
        
        if not leave_type_balance:
            # Fallback to partial match just in case
            leave_type_balance = next(
                (b for b in balances if str(leave_type_id).strip().lower() in str(b.get("type", b.get("leaveType", ""))).strip().lower()),
                None
            )
            
        if not leave_type_balance:
            logger.warning(f"Leave type {leave_type_id} not explicitly found in balance sheet. Proceeding with 0 balance to let backend validate.")
            available_balance = 0.0
        else:
            available_balance = leave_type_balance.get("balance", leave_type_balance.get("available", 0.0))
        
        if available_balance <= 0:
            logger.warning(f"Employee has {available_balance} balance for {leave_type_id}, but proceeding anyway to let backend validate.")
        
        return {
            "status": "ready",
            "payload": {
                "employeeId": user_context.get("employeeId"),
                "type": leave_type_id,
                "startDate": start_date,
                "endDate": end_date,
                "reason": reason or "Personal work"
            },
            "balance_available": available_balance
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
    "analyze_document_from_url",
    "summarize_document_from_url",
    "call_xevyte_api",
    "resolve_relative_date",
    "APIECatalog",
    "WorkflowHelpers"
]
