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
        """Fetch endpoint details by ID. Resolves duplicate IDs by preferring custom endpoints."""
        catalog = cls.load()
        matches = []
        for module_name, module_data in catalog.get("modules", {}).items():
            for endpoint in module_data.get("endpoints", []):
                if endpoint.get("endpoint_id") == endpoint_id:
                    matches.append(endpoint)
        
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0]
            
        # If duplicates exist (e.g. auto-generated vs handwritten), prioritize the one that requires confirmation (mutation)
        for m in matches:
            if m.get("requires_confirmation") is True:
                return m
                
        # If no custom confirmation flag, prioritize POST/PUT over GET
        for m in matches:
            if m.get("method") in ("POST", "PUT", "DELETE", "PATCH"):
                return m
                
        return matches[0]
    
    @classmethod
    def search_by_intent(cls, query: str) -> List[Dict]:
        """Search endpoints by natural language intent with comprehensive indexing and intent alignment"""
        catalog = cls.load()
        query_lower = query.lower().strip()
        query_words = [w for w in query_lower.split() if len(w) > 2]
        
        # Priority detection for Unified Tasks & Approvals
        is_approval_overview_query = any(phrase in query_lower for phrase in [
            "approval", "approvals", "pending approval", "pending approvals", 
            "my approval", "my approvals", "show approval", "show approvals",
            "my task", "my tasks", "pending task", "pending tasks", "unified task", "unified tasks"
        ]) and not any(spec in query_lower for spec in ["leave", "claim", "travel", "ticket", "resignation", "compensation", "hike"])

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
            elif w in ("approval", "approvals"):
                expanded_words.extend(["task", "tasks", "pending", "unified"])

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
                
                # Immediate boost for My Unified Tasks on approval/task queries
                if is_approval_overview_query and ep_id == "getmyunifiedtasks":
                    score += 100
                
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
        
        required_fields = ', '.join(endpoint.get('required_fields', [])) or 'None'
        optional_fields = ', '.join(endpoint.get('optional_fields', [])) or 'None'
        
        return f"""
**Tool Name:** {endpoint.get('api_name', endpoint['endpoint_id'])} (ID: {endpoint['endpoint_id']})
**Description:** {endpoint['description']}
**HTTP Method:** {endpoint.get('method', 'GET')}
**URL Path:** {path}
**Input Schema:**
{path_params_str}- Required JSON Body Fields: {required_fields}
- Optional JSON Body Fields: {optional_fields}

🚨 **ANTI-HALLUCINATION DIRECTIVE**: 
You MUST format your `body` JSON payload to match exactly the required and optional fields above. 
NEVER guess, invent, or hallucinate values for these fields (especially IDs). If you do not have the exact value from the user or a previous tool call (like `getMyTickets`, `getApplicants`), you MUST stop and ask the user or call a GET tool first.

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
# TOOL: ASK CLARIFICATION (FALLBACK / ANTI-HALLUCINATION TOOL)
# ============================================================================

def ask_clarification(question: str, reason: Optional[str] = None) -> Dict[str, Any]:
    """
    Fallback tool: Explicitly halts automated execution to ask the user a clarifying question
    when intent is ambiguous, mandatory information is missing, or no API tool fits the request.
    Use this tool instead of guessing, making up data, or fabricating an API call.
    """
    logger.info(f"Fallback clarification invoked. Reason: {reason}, Question: {question}")
    return {
        "status": "clarification_requested",
        "question": question,
        "reason": reason or "User input is ambiguous or missing required parameters."
    }


# ============================================================================
# TOOL: SEARCH HR KNOWLEDGE BASE (RAG)
# ============================================================================

def search_hr_knowledge_base(query: str) -> str:
    """
    Tool: Search HR policies using RAG system.
    User asks policy questions; agent retrieves company-specific policies.
    """
    logger.info(f"Searching HR KB for: {query}")
    
    settings = get_settings()
    try:
        import urllib.request
        import json
        
        # 1. Get the latest handbook metadata from the Java backend
        url = f"{settings.JAVA_BACKEND_URL}/api/handbook/latest"
        req = urllib.request.Request(url)
        
        with urllib.request.urlopen(req) as response:
            if response.status == 204:
                return "No Employee Handbook has been uploaded by the HR department yet."
            
            data = json.loads(response.read().decode())
            
        download_url = f"http://localhost:8082{data.get('downloadUrl')}"
        file_name = data.get('originalFileName', 'Employee_Handbook.pdf')
        uploaded_at = data.get('uploadedAt', 'Unknown Date')
        
        return (
            f"The HR Knowledge Base policy document is available!\n\n"
            f"**File Name:** {file_name}\n"
            f"**Last Updated:** {uploaded_at}\n\n"
            f"Please inform the user they can download the full policy document here: [Download {file_name}]({download_url})\n\n"
            f"(Note: You cannot read the PDF content directly right now, so just provide the link to the user)."
        )
    except Exception as e:
        logger.error(f"Failed to read HR policies from Java backend: {e}")
        return "Sorry, I could not access the HR knowledge base at this moment. The backend might be unreachable."


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
    Convert relative dates (today, tomorrow, friday, this friday, next monday, 28-08-2026, etc.) to absolute date.
    
    Args:
        date_input: "today", "tomorrow", "friday", "this friday", "next monday", or actual date
        format_output: "dd-MM-yyyy" or "yyyy-MM-dd"
    
    Returns:
        Formatted date string
    """
    if not date_input or not str(date_input).strip():
        date_input = "today"
        
    raw_input = str(date_input).strip()
    lower_input = raw_input.lower()
    
    today = datetime.now().date()
    days_map = {
        "monday": 0, "mon": 0,
        "tuesday": 1, "tue": 1, "tues": 1,
        "wednesday": 2, "wed": 2,
        "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "thrusday": 3, "thrus": 3,
        "friday": 4, "fri": 4,
        "saturday": 5, "sat": 5,
        "sunday": 6, "sun": 6
    }
    
    # Strip common prefixes
    cleaned = lower_input
    for prefix in ("for ", "on ", "this ", "the ", "coming ", "upcoming "):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            
    parsed = None
    
    # 1. Standard relative day phrases
    if lower_input in ("today", "this day") or cleaned in ("today", "this day"):
        parsed = today
    elif lower_input in ("tomorrow", "next day", "the next day", "following day") or cleaned in ("tomorrow", "next day", "the next day", "following day"):
        parsed = today + timedelta(days=1)
    elif lower_input in ("yesterday", "previous day", "the previous day", "day before", "day before day") or cleaned in ("yesterday", "previous day", "the previous day", "day before", "day before day"):
        parsed = today - timedelta(days=1)
    elif lower_input in ("day before yesterday", "the day before yesterday") or cleaned in ("day before yesterday", "the day before yesterday"):
        parsed = today - timedelta(days=2)
    elif lower_input in ("day after tomorrow", "the day after tomorrow") or cleaned in ("day after tomorrow", "the day after tomorrow"):
        parsed = today + timedelta(days=2)
    # 2. "next <day>" / "next <mon/tue/...>"
    elif lower_input.startswith("next ") or cleaned.startswith("next "):
        day_str = (cleaned if cleaned.startswith("next ") else lower_input).replace("next ", "").strip()
        if day_str in days_map:
            target_day = days_map[day_str]
            current_day = today.weekday()
            days_ahead = (target_day - current_day) % 7
            if days_ahead == 0:
                days_ahead = 7
            else:
                days_ahead += 7
            parsed = today + timedelta(days=days_ahead)
        else:
            raise ValueError(f"Unknown day: {day_str}")
    # 3. Direct weekday names or abbreviations (e.g., "fri", "friday", "this fri")
    elif cleaned in days_map:
        target_day = days_map[cleaned]
        current_day = today.weekday()
        days_ahead = (target_day - current_day) % 7
        parsed = today + timedelta(days=days_ahead)
    # 4. Offsets like "3 days", "in 2 weeks", "4 days later"
    elif " days" in lower_input or " weeks" in lower_input or " day" in lower_input:
        import re
        match = re.search(r"(\d+)\s*(days?|weeks?)", lower_input)
        if match:
            num = int(match.group(1))
            unit = match.group(2)
            delta_days = num * 7 if "week" in unit else num
            if "ago" in lower_input or "before" in lower_input:
                parsed = today - timedelta(days=delta_days)
            else:
                parsed = today + timedelta(days=delta_days)
        else:
            raise ValueError(f"Cannot parse relative offset: {date_input}")
    # 5. Explicit date formats
    else:
        import re
        if not re.search(r"\d", raw_input):
            raise ValueError(f"Unknown date format: {date_input}")
        try:
            # Check for mm/yyyy/dd format (e.g. 08/2026/28 or 8-2026-28)
            mm_yyyy_dd_match = re.match(r"^(\d{1,2})[-/.](\d{4})[-/.](\d{1,2})$", raw_input)
            if mm_yyyy_dd_match:
                m_val = int(mm_yyyy_dd_match.group(1))
                y_val = int(mm_yyyy_dd_match.group(2))
                d_val = int(mm_yyyy_dd_match.group(3))
                import datetime as dt_module
                parsed = dt_module.date(y_val, m_val, d_val)
            elif re.match(r"^\d{4}[-/.]", raw_input):
                # ISO yyyy/mm/dd or yyyy-mm-dd
                parsed = parser.parse(raw_input, dayfirst=False)
            else:
                # Standard dd/mm/yyyy or dd-mm-yyyy
                parsed = parser.parse(raw_input, dayfirst=True)
        except Exception:
            raise ValueError(f"Unknown date format: {date_input}")
    
    # Convert to datetime / date if needed
    if isinstance(parsed, str):
        if re.match(r"^\d{4}[-/.]", parsed):
            parsed = parser.parse(parsed, dayfirst=False).date()
        else:
            parsed = parser.parse(parsed, dayfirst=True).date()
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

    # Initialize body for POST/PUT if it's None so required fields can be injected and checked
    if method in ("POST", "PUT", "PATCH") and body is None:
        body = {}

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
            all_tasks = await WorkflowHelpers.build_my_tasks(user_context, token)
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
            body["role"] = user_context.get("role") or "MANAGER"
            
        # Force exact Java enum/string values for action
        body["action"] = "Reject" if endpoint_id == "rejectLeave" else "Approve"
        if endpoint_id == "rejectLeave" and "remarks" not in body:
            body["remarks"] = body.get("reason") or body.get("comment") or "Rejected by manager"

        # Auto-resolve leaveRequestId if missing or non-digit
        cur_req_id = str(body.get("leaveRequestId", ""))
        if not cur_req_id or not cur_req_id.isdigit():
            all_tasks = await WorkflowHelpers.build_my_tasks(user_context, token)
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

    if endpoint_id == "submitResignation" and body is not None:
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

    if body is not None and endpoint_id not in ("submitEntry", "updateEntry", "applyLeave"): # These fields will be auto-injected
        # Combine all parameter sources to prevent false validation blocks
        all_params = {}
        if isinstance(body, dict):
            all_params.update(body)
        if path_params:
            all_params.update(path_params)
        if query_params:
            all_params.update(query_params)
            
        # Treat context-injectable parameters as present
        if user_context.get("employeeId"):
            all_params["employeeId"] = all_params.get("employeeId") or user_context["employeeId"]
            all_params["approverId"] = all_params.get("approverId") or user_context["employeeId"]
            all_params["managerId"] = all_params.get("managerId") or user_context["employeeId"]
        if user_context.get("role"):
            all_params["role"] = all_params.get("role") or user_context["role"]
        else:
            all_params["role"] = all_params.get("role") or "MANAGER"

        missing = [f for f in required_fields if f not in all_params]
        if missing:
            return {
                "status": "incomplete",
                "error": f"Missing required fields: {', '.join(missing)}",
                "endpoint_id": endpoint_id
            }
    
    # ========================================================================
    
    # Special handling for Recent Activities Aggregator
    
    if endpoint_id == "getMyUnifiedTasks":
        tasks = await WorkflowHelpers.build_my_tasks(user_context, token)
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
        # Remap common field names to exact Java entity fields
        if "startDate" in body: body["allocationDate"] = body.pop("startDate")
        if "endDate" in body: body["expectedReturnDate"] = body.pop("endDate")
        
        # Remap 'condition' to 'conditionAtIssue'
        if "condition" in body: 
            body["conditionAtIssue"] = body.pop("condition")
        elif isinstance(body.get("asset"), dict) and "condition" in body["asset"]:
            body["conditionAtIssue"] = body["asset"].pop("condition")
        
        # Remove COMPLETELY hallucinated fields (like resource allocation percentages)
        body.pop("allocationPercentage", None)
        
        missing = []
        if "assetId" not in body and "asset" not in body:
            missing.append("Asset ID")
        if "employeeId" not in body and "employee" not in body:
            missing.append("Employee ID")
        if "conditionAtIssue" not in body:
            missing.append("Condition at Issue (e.g. Good, New, Scratched)")
            
        if missing:
            return {
                "status": "error",
                "error": f"Missing mandatory fields for asset allocation. You MUST ask the user for: {', '.join(missing)}"
            }
            
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
                    
        # Special handling for Expense Claims (submitClaim/saveClaim)
        if endpoint_id in ("submitClaim", "saveClaim", "saveDraftClaim") and method == "POST":
            cat_id = str(body.get("category", ""))
            missing_fields = []
            
            # Map of required fields per category ID
            # 1: Travel, 2: Accommodation, 3: Food, 4: Fuel, 5: Others
            if cat_id == "1":
                for f in ["mode", "tripCategory", "fromLocation", "toLocation", "purpose"]:
                    if not body.get(f): missing_fields.append(f)
            elif cat_id == "2":
                for f in ["city", "hotelName", "checkInDate", "checkOutDate", "nights", "purpose"]:
                    if not body.get(f): missing_fields.append(f)
            elif cat_id == "3":
                for f in ["mealType", "numberOfPeople"]:
                    if not body.get(f): missing_fields.append(f)
            elif cat_id == "4":
                for f in ["vehicle", "vehicleType", "purpose", "startLocation", "endLocation", "distanceKm", "ratePerKm"]:
                    if not body.get(f): missing_fields.append(f)
            elif cat_id == "5":
                for f in ["subCategory", "justification"]:
                    if not body.get(f): missing_fields.append(f)
                    
            if missing_fields:
                return {
                    "status": "error",
                    "error": f"Missing category-specific fields. You MUST ask the user for these fields before proceeding: {', '.join(missing_fields)}"
                }
                
        # Special handling for IT Declaration (saveOrUpdate)
        if endpoint_id == "saveOrUpdate" and "it-declarations" in actual_path and method == "POST" and body:
            emp_id = user_context.get("employeeId") or "scaloz_admin"
            fy = body.get("financialYear")
            new_regime = body.get("taxRegime")
            
            # Format tax regime correctly
            if new_regime:
                if new_regime.lower() == "new regime": body["taxRegime"] = "NEW_REGIME"
                elif new_regime.lower() == "old regime": body["taxRegime"] = "OLD_REGIME"
                
            if emp_id and fy:
                # Check if it exists to enforce tax regime rule
                try:
                    settings = get_settings()
                    check_url = f"{settings.JAVA_BACKEND_URL}/api/it-declarations/{emp_id}/{fy}"
                    headers = {}
                    if token: headers["Authorization"] = f"Bearer {token}"
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        resp = await client.get(check_url, headers=headers)
                        if resp.status_code == 200:
                            existing = resp.json()
                            if existing and isinstance(existing, dict):
                                existing_regime = existing.get("taxRegime")
                                if existing_regime and new_regime and existing_regime.lower() != new_regime.lower():
                                    return {
                                        "status": "error",
                                        "error": f"RULE VIOLATION: Tax regime is allowed to select only once in a financial year. Employee already selected {existing_regime} for {fy}. You CANNOT change it to {new_regime}."
                                    }
                except Exception as e:
                    logger.warning(f"Failed to check existing IT declaration: {e}")
            
            # Enforce status field explicitly
            status = body.get("status")
            if not status:
                return {
                    "status": "error",
                    "error": "Missing 'status' field. You MUST explicitly ask the user if they want to save this as a 'Draft' or 'Submitted'."
                }
            elif status.lower() == "submit":
                body["status"] = "Submitted"

        # Special handling for Attendance (submitEntry / updateEntry)
        if endpoint_id == "submitEntry" and method == "POST":
            b = body or {}
            loc = b.get("workLocation") or b.get("location")
            if not loc or str(loc).strip().lower() in ("none", "null", ""):
                return {
                    "status": "user_input_required",
                    "status_code": 200,
                    "data": "Missing required field: workLocation.\nPlease ask the user: 'Where are you checking in from today? (e.g. Office, WFH, Client Site)'"
                }
                
        if endpoint_id == "updateEntry" and method == "PUT":
            b = body or {}
            loc = b.get("logoutWorkLocation") or b.get("workLocation") or b.get("location")
            if not loc or str(loc).strip().lower() in ("none", "null", ""):
                return {
                    "status": "user_input_required",
                    "status_code": 200,
                    "data": "Missing required field: logoutWorkLocation.\nPlease ask the user: 'Where are you checking out from? (e.g. Office, WFH, Client Site)'"
                }
                
        # Special handling for Leave Application (applyLeave)
        if endpoint_id == "applyLeave" and method == "POST":
            b = body or {}
            start_val = b.get("startDate") or b.get("fromDate") or b.get("start_date") or b.get("from_date") or "today"
            end_val = b.get("endDate") or b.get("toDate") or b.get("end_date") or b.get("to_date") or start_val
            type_val = b.get("type") or b.get("leaveType") or b.get("leave_type") or b.get("leaveTypeId")
            reason_val = b.get("reason") or b.get("comments") or b.get("remarks")
            
            type_missing = not type_val or str(type_val).strip().lower() in ("none", "null", "")
            reason_missing = not reason_val or str(reason_val).strip().lower() in ("none", "null", "")
            
            # If leave type or reason is missing, do NOT default silently. Fetch balances and prompt user!
            if type_missing or reason_missing:
                bal_resp = await call_xevyte_api("getDetailedLeaveBalance", user_context=user_context, token=token)
                balances_list = []
                if bal_resp.get("status") == "success" and isinstance(bal_resp.get("data"), list):
                    for bl in bal_resp["data"]:
                        b_type = bl.get("type") or bl.get("leaveType")
                        b_cnt = bl.get("balance", bl.get("available", 0))
                        if b_type:
                            balances_list.append(f"{b_type} (Balance: {b_cnt})")
                balances_summary = ", ".join(balances_list) if balances_list else "Casual Leave, Sick Leave, Earned Leave"
                
                missing_fields = []
                if type_missing:
                    missing_fields.append("Leave Type")
                if reason_missing:
                    missing_fields.append("Reason")
                
                formatted_start = resolve_relative_date(start_val, "dd-MM-yyyy")
                formatted_end = resolve_relative_date(end_val, "dd-MM-yyyy")
                date_display = formatted_start if formatted_start == formatted_end else f"{formatted_start} to {formatted_end}"
                
                return {
                    "status": "user_input_required",
                    "status_code": 200,
                    "data": (
                        f"Missing required leave details ({', '.join(missing_fields)}) for {date_display}.\n"
                        f"Please ask the user: Which leave type would you like to apply for? (Available: {balances_summary}) And what is the reason for the leave?"
                    )
                }

            try:
                leave_result = await WorkflowHelpers.collect_leave_data(
                    user_context, token,
                    start_val,
                    end_val,
                    type_val,
                    reason_val
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
                "message": "Action prepared and queued for confirmation. If the user requested MULTIPLE actions (batch approve/reject), continue calling tools for the remaining actions NOW. Once ALL actions are queued, output a summary and tell the user to click the Approve button.",
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
                            with open(v, "rb") as f:
                                files["profilePic"] = (os.path.basename(v), f.read(), "image/jpeg")
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
                        with open(receipt_path, "rb") as f:
                            files["receiptFile"] = (os.path.basename(receipt_path), f.read(), "application/octet-stream")
                        
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

                # Enrich leave lists when employeeName is missing/null
                if isinstance(resp_data, list) and ("leaves" in actual_path or "Leave" in endpoint_id):
                    for leave_item in resp_data:
                        if isinstance(leave_item, dict):
                            emp_n = leave_item.get("employeeName")
                            if not emp_n or str(emp_n).strip().lower() in ("null null", "null", "none", "unknown", ""):
                                leave_item["employeeName"] = leave_item.get("employeeId") or user_context.get("name") or "Employee"

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
                    msa_doc_blob = cust_dict.pop("msaDocBlob", None)
                    cid = cust_dict.get("customerId") or cust_dict.get("id") or cust_dict.get("tenantCustomerId")
                    if cid:
                        if msa_doc_blob:
                            import base64, uuid, os
                            try:
                                pdf_data = base64.b64decode(msa_doc_blob)
                                os.makedirs("downloads", exist_ok=True)
                                fn = f"msa_{cid}_{uuid.uuid4().hex[:6]}.pdf"
                                with open(os.path.join("downloads", fn), "wb") as f:
                                    f.write(pdf_data)
                                cust_dict["msaDownloadUrl"] = f"/downloads/{fn}"
                            except Exception:
                                cust_dict["msaDownloadUrl"] = f"/api/customers/{cid}/download"
                        else:
                            cust_dict["msaDownloadUrl"] = f"/api/customers/{cid}/download"
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
                    sow_doc_blob = sow_dict.pop("sowDocBlob", None)
                    sow_dict.pop("sowDoc", None)
                    sid = sow_dict.get("sowId") or sow_dict.get("id")
                    if sid:
                        if sow_doc_blob:
                            import base64, uuid, os
                            try:
                                pdf_data = base64.b64decode(sow_doc_blob)
                                os.makedirs("downloads", exist_ok=True)
                                fn = f"sow_{sid}_{uuid.uuid4().hex[:6]}.pdf"
                                with open(os.path.join("downloads", fn), "wb") as f:
                                    f.write(pdf_data)
                                sow_dict["sowDownloadUrl"] = f"/downloads/{fn}"
                            except Exception:
                                sow_dict["sowDownloadUrl"] = f"/api/sows/{sid}/download"
                        else:
                            sow_dict["sowDownloadUrl"] = f"/api/sows/{sid}/download"
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

                if isinstance(resp_data, dict) and (resp_data.get("status") == "error" or str(resp_data.get("status")).lower() == "failed" or resp_data.get("success") is False):
                    error_msg = resp_data.get("error") or resp_data.get("message") or resp_data.get("detail") or str(resp_data)
                    return {
                        "status": "error",
                        "status_code": response.status_code,
                        "error": error_msg,
                        "suggestion": _get_error_suggestion(response.status_code, endpoint_id)
                    }

                # ============================================================
                # UNIVERSAL SOFT-ERROR DETECTION FOR ALL MUTATIONS
                # Java Spring Boot often returns 200 OK even when the action
                # silently failed. This catches those cases for EVERY
                # POST/PUT/DELETE endpoint, not just approvals.
                # ============================================================
                if method in ("POST", "PUT", "DELETE", "PATCH"):
                    # 1. Empty/null response on a mutation is always suspicious
                    if resp_data is None or resp_data == "" or resp_data == "null":
                        return {
                            "status": "error",
                            "status_code": response.status_code,
                            "error": f"The Java backend returned an empty response for '{endpoint_id}'. The action may not have been executed. Please verify the status manually.",
                            "suggestion": f"Re-check the current status to confirm whether the action for '{endpoint_id}' was actually applied."
                        }

                    # 2. String response containing error keywords
                    if isinstance(resp_data, str):
                        lower_resp = resp_data.lower()
                        ERROR_KEYWORDS = (
                            "invalid action", "no action taken", "already approved",
                            "already rejected", "not found", "not authorized",
                            "access denied", "forbidden", "cannot process",
                            "validation failed", "constraint violation",
                            "duplicate entry", "already exists", "not allowed",
                            "insufficient", "expired", "no records",
                            "failed to", "unable to", "error occurred",
                            "internal server error", "bad request"
                        )
                        if any(kw in lower_resp for kw in ERROR_KEYWORDS):
                            return {
                                "status": "error",
                                "status_code": response.status_code,
                                "error": f"Action '{endpoint_id}' failed: {resp_data}",
                                "suggestion": "The Java backend indicated the action was not successful. Please check the exact error above."
                            }

                    # 3. Dict response with hidden error indicators
                    if isinstance(resp_data, dict):
                        msg_val = str(resp_data.get("message", "")).lower()
                        detail_val = str(resp_data.get("detail", "")).lower()
                        combined = msg_val + " " + detail_val
                        DICT_ERROR_KEYWORDS = (
                            "not authorized", "cannot", "failed", "invalid",
                            "not found", "denied", "not allowed", "expired",
                            "already exists", "duplicate", "constraint",
                            "insufficient", "no records"
                        )
                        if any(kw in combined for kw in DICT_ERROR_KEYWORDS):
                            err_text = resp_data.get("message") or resp_data.get("detail") or str(resp_data)
                            return {
                                "status": "error",
                                "status_code": response.status_code,
                                "error": f"Action '{endpoint_id}' failed: {err_text}",
                                "suggestion": "The Java backend returned a success status code but the response body indicates a failure."
                            }

                return {
                    "status": "success",
                    "status_code": response.status_code,
                    "data": resp_data
                }
            
            # Error response
            else:
                # SPECIAL CASE: If getHolidaysByEmployeeLocation returns 400 (e.g. employee has no workLocation),
                # just return an empty list so the Agent doesn't say "server error" and instead politely says "no holidays".
                if endpoint_id == "getHolidaysByEmployeeLocation" and response.status_code == 400:
                    return {
                        "status": "success",
                        "status_code": 200,
                        "data": []
                    }
                    
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
    async def build_my_tasks(user_context: dict, token: str) -> list:
        emp_id = user_context.get("employeeId")
        headers = {"Authorization": f"Bearer {token}"}
        tasks = []
        backend_url = get_settings().JAVA_BACKEND_URL
        
        try:
            seen_leave_ids = set()
            
            def _process_leave(l):
                if l.get("id") in seen_leave_ids: return
                seen_leave_ids.add(l.get("id"))
                emp_name = l.get("employeeName")
                if not emp_name or str(emp_name).strip().lower() in ("null null", "null", "none", "unknown", ""):
                    emp_name = l.get("employeeId") or "Unknown Employee"

                leave_type = l.get("type") or l.get("leaveType")
                if not leave_type or str(leave_type).strip().lower() in ("none", "null", ""):
                    leave_type = "Leave"

                ref_id = l.get("leaveReference") or l.get("referenceId")
                if not ref_id or str(ref_id).strip().lower() in ("n/a", "none", "null", ""):
                    ref_id = f"LV-{l.get('id')}"
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

            async with httpx.AsyncClient(timeout=8.0) as client:
                # 1. Leaves (Manager + HR)
                try:
                    r_leaves_mgr = await client.get(f"{backend_url}/api/leaves/manager/{emp_id}", headers=headers)
                    if r_leaves_mgr.status_code == 200:
                        for l in r_leaves_mgr.json():
                            status = str(l.get("status", "")).lower()
                            if status == "pending level 1" or status == "pending":
                                _process_leave(l)
                except Exception as e:
                    logger.debug(f"Could not fetch manager leaves: {e}")

                try:
                    r_leaves_hr = await client.get(f"{backend_url}/api/leaves/hr/{emp_id}", headers=headers)
                    if r_leaves_hr.status_code == 200:
                        for l in r_leaves_hr.json():
                            status = str(l.get("status", "")).lower()
                            if status not in ("rejected", "cancelled", "pending level 1", "pending"):
                                _process_leave(l)
                except Exception as e:
                    logger.debug(f"Could not fetch hr leaves: {e}")

                # 2. Claims
                try:
                    r_claims = await client.get(f"{backend_url}/api/claims/manager/{emp_id}", headers=headers)
                    if r_claims.status_code == 200:
                        for c in r_claims.json():
                            if "pending" in str(c.get("status", "")).lower():
                                emp_name = c.get("employeeName")
                                if not emp_name or str(emp_name).strip().lower() in ("null null", "null", "none", "unknown", ""):
                                    emp_name = c.get("employeeId") or "Unknown Employee"

                                exp_type = c.get("expenseType") or "Claim"
                                amt = c.get("amount") or "0"
                                ref_id = c.get("claimGroupId") or c.get("referenceId")
                                if not ref_id or str(ref_id).strip().lower() in ("n/a", "none", "null", ""):
                                    ref_id = f"CLM-{c.get('id')}"

                                tasks.append({
                                    "ID": c.get("id"),
                                    "Reference ID": ref_id,
                                    "Type": "Claim Approval",
                                    "Leave Type": exp_type,
                                    "Employee": emp_name,
                                    "Details": f"{exp_type} - {amt}",
                                    "Date": c.get("expenseDate", c.get("appliedOn", c.get("createdAt", c.get("date", "N/A"))))
                                })
                except Exception as e:
                    logger.debug(f"Could not fetch claims: {e}")

                # 3. Travel (Manager Pending)
                try:
                    r_travel = await client.get(f"{backend_url}/api/travel/manager/pending/{emp_id}", headers=headers)
                    if r_travel.status_code == 200:
                        for t in r_travel.json():
                            emp_name = t.get("employeeName")
                            if not emp_name or str(emp_name).strip().lower() in ("null null", "null", "none", "unknown", ""):
                                emp_name = t.get("employeeId") or "Unknown Employee"

                            purpose = t.get("purposeOfTravel") or t.get("purpose") or "Travel"
                            from_loc = t.get("fromLocation") or "N/A"
                            to_loc = t.get("toLocation") or t.get("destination") or "N/A"
                            mode = t.get("modeOfTravel") or "Trip"
                            ref_id = t.get("referenceId")
                            if not ref_id or str(ref_id).strip().lower() in ("n/a", "none", "null", ""):
                                ref_id = f"TRV-{t.get('id')}"

                            tasks.append({
                                "ID": t.get("id"),
                                "Reference ID": ref_id,
                                "Type": "Travel Approval",
                                "Leave Type": purpose,
                                "Employee": emp_name,
                                "Details": f"{mode} ({from_loc} -> {to_loc}) - {purpose}",
                                "Date": t.get("createdAt", t.get("requestDate", "N/A"))
                            })
                except Exception as e:
                    logger.debug(f"Could not fetch travel tasks: {e}")

                # 3b. Travel Admin Assigned
                try:
                    r_travel_admin = await client.get(f"{backend_url}/api/travel/admin/assigned-requests/{emp_id}", headers=headers)
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
                    logger.debug(f"Could not fetch travel admin tasks: {e}")

                # 4. Tickets
                try:
                    r_tickets = await client.get(f"{backend_url}/api/tickets/manager/{emp_id}", headers=headers)
                    if r_tickets.status_code == 200:
                        for tk in r_tickets.json():
                            if "pending" in str(tk.get("status", "")).lower() or "open" in str(tk.get("status", "")).lower():
                                emp_name = tk.get("employeeName")
                                if not emp_name or str(emp_name).strip().lower() in ("null null", "null", "none", "unknown", ""):
                                    emp_name = tk.get("employeeId") or "Unknown Employee"

                                details = tk.get("title") or tk.get("subject") or "Helpdesk Ticket"
                                ref_id = tk.get("ticketNumber") or tk.get("referenceId")
                                if not ref_id or str(ref_id).strip().lower() in ("n/a", "none", "null", ""):
                                    ref_id = f"TKT-{tk.get('id')}"

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
                    logger.debug(f"Could not fetch tickets: {e}")

                # 5. Exit/Resignation Tasks
                try:
                    headers_exit = dict(headers)
                    headers_exit["managerId"] = emp_id
                    headers_exit["employeeId"] = emp_id
                    r_exits = await client.get(f"{backend_url}/api/v1/exit-management/manager/pending-resignations", headers=headers_exit)
                    if r_exits.status_code == 200:
                        for ex in r_exits.json():
                            if ex.get("status") != "Final Approved - Exit Complete":
                                emp_name = ex.get("employeeName")
                                if not emp_name or str(emp_name).strip().lower() in ("null null", "null", "none", "unknown", ""):
                                    emp_name = ex.get("employeeId") or "Unknown Employee"

                                ref_id = ex.get("referenceId")
                                if not ref_id or str(ref_id).strip().lower() in ("n/a", "none", "null", ""):
                                    ref_id = f"EXT-{ex.get('id')}"

                                date_val = ex.get("submissionDate") or ex.get("createdDate") or ex.get("createdAt")
                                tasks.append({
                                    "ID": ex.get("id"),
                                    "Reference ID": ref_id,
                                    "Type": "Exit/Resignation Approval",
                                    "Leave Type": "Resignation",
                                    "Employee": emp_name,
                                    "Details": f"Resignation Date: {ex.get('resignationDate') or ex.get('lastWorkingDay') or 'N/A'}",
                                    "Date": date_val if date_val else "N/A"
                                })
                except Exception as e:
                    logger.debug(f"Could not fetch exit tasks: {e}")

                # 6. Compensation Proposals
                try:
                    r_comp = await client.get(f"{backend_url}/api/compensation/approver/{emp_id}", headers=headers)
                    if r_comp.status_code == 200:
                        comp_data = r_comp.json()
                        if isinstance(comp_data, list):
                            for comp in comp_data:
                                c_status = str(comp.get("status", "")).lower()
                                if "pending" in c_status or "proposed" in c_status or "details" in c_status or not c_status:
                                    emp_name = comp.get("employeeName") or comp.get("name")
                                    if not emp_name or str(emp_name).strip().lower() in ("null null", "null", "none", "unknown", ""):
                                        emp_name = comp.get("employeeId") or "Unknown Employee"

                                    hike = comp.get("hikePercentage") or comp.get("hike") or ""
                                    hike_str = f" ({hike}% Hike)" if hike else ""
                                    ref_id = comp.get("referenceId")
                                    if not ref_id or str(ref_id).strip().lower() in ("n/a", "none", "null", ""):
                                        ref_id = f"CMP-{comp.get('id')}"

                                    tasks.append({
                                        "ID": comp.get("id"),
                                        "Reference ID": ref_id,
                                        "Type": "Compensation Approval",
                                        "Leave Type": "Hike Proposal",
                                        "Employee": emp_name,
                                        "Details": f"Designation: {comp.get('designation', 'N/A')}{hike_str}",
                                        "Date": comp.get("effectiveDate", comp.get("createdAt", "N/A"))
                                    })
                except Exception as e:
                    logger.debug(f"Could not fetch compensation tasks: {e}")
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
        start_date = resolve_relative_date(start_date_str or "today", "dd-MM-yyyy")
        end_date = resolve_relative_date(end_date_str or start_date_str or "today", "dd-MM-yyyy")
        
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
        
        emp_name = user_context.get("name") or user_context.get("employeeName") or user_context.get("employeeId")
        return {
            "status": "ready",
            "payload": {
                "employeeId": user_context.get("employeeId"),
                "employeeName": emp_name,
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
                    # Fallback if agent passed wrong ID (e.g., employeeId instead of entryId)
                    if not existing_entry:
                        today_dmy = now.strftime("%d-%m-%Y")
                        today_ymd = now.strftime("%Y-%m-%d")
                        for e in entries:
                            e_date = e.get("date")
                            if e_date in (today_dmy, today_ymd) and e.get("status") != "CHECKED_OUT":
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
                from dateutil import parser
                login_dt = parser.parse(login_time_str)
                logout_dt = parser.parse(time_str)
                diff = logout_dt - login_dt
                if diff.total_seconds() < 0:
                    diff += datetime.timedelta(days=1)
                hours = diff.total_seconds() / 3600.0
                payload["totalHours"] = round(hours, 2)
        except Exception as e:
            logger.warning(f"Failed to calculate totalHours during checkout: {e}")
            payload["totalHours"] = 0.0
            
        return payload

async def prepare_batch_approvals(actions: List[Dict[str, Any]], user_context: dict, token: str) -> dict:
    pending_actions = []
    errors = []
    seen_tasks = set()
    
    # Fetch actual pending tasks to validate and auto-resolve types
    try:
        pending_list = await WorkflowHelpers.build_my_tasks(user_context, token)
    except Exception as e:
        logger.error(f"Failed to fetch pending tasks in prepare_batch_approvals: {e}")
        return {
            "status": "error",
            "error": f"Failed to fetch pending tasks: {e}"
        }
        
    # Map IDs and Reference IDs to tasks
    pending_by_id = {}
    for t in pending_list:
        t_id = t.get("ID")
        ref_id = t.get("Reference ID")
        if t_id is not None:
            pending_by_id[str(t_id)] = t
        if ref_id:
            pending_by_id[str(ref_id).strip().upper()] = t

    for action_item in actions:
        task_id_raw = action_item.get("task_id")
        if not task_id_raw:
            errors.append("Missing task_id in action item")
            continue
            
        task_id_str = str(task_id_raw).strip()
        if task_id_str in seen_tasks:
            continue
        seen_tasks.add(task_id_str)
        matched_task = None
        
        if task_id_str in pending_by_id:
            matched_task = pending_by_id[task_id_str]
        elif task_id_str.upper() in pending_by_id:
            matched_task = pending_by_id[task_id_str.upper()]
        else:
            # Extract digits to match numeric ID
            digits = "".join(c for c in task_id_str if c.isdigit())
            if digits and digits in pending_by_id:
                matched_task = pending_by_id[digits]
                
        if not matched_task:
            fallback_type = action_item.get("type") or action_item.get("task_type") or action_item.get("taskType")
            if fallback_type and any(k in str(fallback_type).lower() for k in ["leave", "claim", "travel", "exit", "resignation", "ticket", "compensation", "hike"]):
                digits = "".join(c for c in task_id_str if c.isdigit())
                task_id = int(digits) if digits else task_id_raw
                task_type = str(fallback_type)
            else:
                errors.append(f"Task ID '{task_id_raw}' is not in your pending approvals list.")
                continue
        else:
            task_id = matched_task.get("ID")
            task_type = matched_task.get("Type")
        act_value = str(action_item.get("action", "")).strip().capitalize() # "Approve" or "Reject"
        comment = action_item.get("comment", "") or action_item.get("reason", "") or action_item.get("comments", "")
        
        endpoint_id = None
        path_params = None
        query_params = None
        body = None
        
        if "leave" in task_type.lower():
            endpoint_id = "approveLeave" if act_value == "Approve" else "rejectLeave"
            body = {
                "leaveRequestId": task_id,
                "action": act_value,
                "role": user_context.get("role") or "MANAGER",
                "approverId": user_context.get("employeeId", "")
            }
            if act_value == "Reject":
                body["remarks"] = comment or "Rejected by manager"
        elif "claim" in task_type.lower():
            endpoint_id = "approveClaim" if act_value == "Approve" else "rejectClaim"
            path_params = {"id": task_id}
            query_params = {
                "role": "Manager",
                "approverId": user_context.get("employeeId", "")
            }
            if act_value == "Reject":
                query_params["reason"] = comment or "Rejected by manager"
        elif "travel" in task_type.lower() or "booking" in task_type.lower():
            if "admin" in task_type.lower() or "booking" in task_type.lower():
                if act_value == "Reject":
                    endpoint_id = "rejectRequestByAdmin"
                    path_params = {"id": task_id}
                    query_params = {
                        "adminId": user_context.get("employeeId", ""),
                        "rejectedReason": comment or "Rejected by travel admin"
                    }
                    if len(query_params["rejectedReason"]) < 10:
                        query_params["rejectedReason"] = f"Rejected: {query_params['rejectedReason']} (declined by travel admin)"
                else:
                    endpoint_id = "uploadMultipleFiles"
                    path_params = {"requestId": task_id}
            else:
                endpoint_id = "approveRequest" if act_value == "Approve" else "rejectRequest"
                path_params = {"id": task_id}
                query_params = {
                    "managerId": user_context.get("employeeId", "")
                }
                if act_value == "Reject":
                    query_params["rejectedReason"] = comment or "Rejected by manager due to budget limit"
        elif "exit" in task_type.lower() or "resignation" in task_type.lower():
            endpoint_id = "approveResignationByManager" if act_value == "Approve" else "rejectResignationByManager"
            path_params = {"id": task_id}
            if act_value == "Reject":
                body = {"comments": comment or "Rejected by manager"}
        elif "ticket" in task_type.lower():
            endpoint_id = "managerApproveTicket" if act_value == "Approve" else "managerRejectTicket"
            path_params = {"ticketId": task_id}
            if act_value == "Reject":
                query_params = {"reason": comment or "Rejected by manager"}
        elif "compensation" in task_type.lower():
            endpoint_id = "approveCompensation" if act_value == "Approve" else "rejectCompensation"
            body = {"id": task_id}
            if act_value == "Reject":
                body["comments"] = comment or "Rejected by manager"
        else:
            errors.append(f"Unknown task type: {task_type}")
            continue
            
        # Get details from catalog for this endpoint
        endpoint_data = APIECatalog().get_endpoint(endpoint_id)
        if not endpoint_data:
            errors.append(f"Endpoint '{endpoint_id}' not found in catalog")
            continue
            
        # Resolve actual path parameters to avoid placeholders in the action_data
        method = endpoint_data.get("method", "GET").upper()
        path = endpoint_data.get("path", "")
        actual_path = path
        if path_params:
            for k, v in path_params.items():
                actual_path = actual_path.replace(f"{{{k}}}", str(v))
                
        # Handle special parameter injections that tools.py does in call_xevyte_api
        if endpoint_id in ("approveClaim", "rejectClaim") and query_params:
            cur_role = str(query_params.get("role", "")).lower()
            query_params["role"] = "Finance" if "finance" in cur_role else "Manager"
            
        if endpoint_id in ("approveRequest", "rejectRequest") and query_params:
            if endpoint_id == "rejectRequest":
                r_reason = query_params.get("rejectedReason") or "Rejected by manager due to budget limit"
                if len(r_reason) < 10:
                    r_reason = f"Rejected: {r_reason} (exceeds budget limit)"
                query_params["rejectedReason"] = r_reason

        # Build action data dict matching confirmation format
        action_data = {
            "endpoint_id": endpoint_id,
            "method": method,
            "path": actual_path,
            "query_params": query_params,
            "body": body
        }
        pending_actions.append(action_data)
        
    if errors and not pending_actions:
        return {
            "status": "error",
            "error": "; ".join(errors)
        }
        
    return {
        "status": "pending_confirmation",
        "batch_actions": pending_actions,
        "message": f"Successfully prepared {len(pending_actions)} actions." + (f" Errors: {'; '.join(errors)}" if errors else "")
    }

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
    "WorkflowHelpers",
    "prepare_batch_approvals"
]
