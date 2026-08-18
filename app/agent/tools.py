import json
import logging
from typing import Dict, Any, Optional

import httpx

from app.config import get_settings
from app.catalog.search import catalog_search
from app.rag.retriever import retriever
from app.agent.confirmation import generate_confirmation_token

logger = logging.getLogger("xeva.agent.tools")

def search_api_catalog(query: str) -> str:
    """Tool: Search the API catalog for relevant endpoints."""
    results = catalog_search.search_by_intent(query)
    if not results:
        return "No matching endpoints found in the catalog."
        
    out = []
    for entry in results:
        out.append(entry.to_tool_description())
    return "\n\n".join(out)

def search_hr_knowledge_base(query: str) -> str:
    """Tool: Search the HR policies RAG system."""
    return retriever.search(query)

async def call_xevyte_api(
    endpoint_id: str,
    method: str,
    path: str,
    user_context: Dict[str, Any],
    path_params: Optional[Dict[str, Any]] = None,
    query_params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    token: Optional[str] = None
) -> str:
    """
    Tool: Call the Java backend API.
    Intersects POST/PUT/DELETE methods to require confirmation.
    """
    # 1. Resolve path parameters
    actual_path = path
    if path_params:
        for k, v in path_params.items():
            actual_path = actual_path.replace(f"{{{k}}}", str(v))
            
    # Always try to inject employeeId if it's missing but needed
    if "{employeeId}" in actual_path and user_context.get("employeeId"):
        actual_path = actual_path.replace("{employeeId}", user_context["employeeId"])
        
    method = method.upper()
    
    # 2. Check if this is a mutation (requires confirmation)
    if method in ("POST", "PUT", "DELETE", "PATCH"):
        # --- HARDCODED WORKAROUND FOR CHECK-OUT (updateEntry) ---
        if endpoint_id == "updateEntry" and method == "PUT" and body:
            emp_id = user_context.get("employeeId")
            if emp_id:
                try:
                    settings = get_settings()
                    get_url = f"{settings.java_backend_url}/api/daily-entry/employee/{emp_id}"
                    get_headers = {"Content-Type": "application/json"}
                    if token:
                        get_headers["Authorization"] = f"Bearer {token}"
                        
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.get(get_url, headers=get_headers)
                        if resp.status_code == 200:
                            entries = resp.json()
                            entry_id_str = actual_path.split("/")[-1]
                            for e in entries:
                                if str(e.get("id")) == entry_id_str:
                                    # Merge existing data with the new fields
                                    merged_body = dict(e)
                                    merged_body.update(body)
                                    body = merged_body
                                    break
                except Exception as ex:
                    logger.error(f"Failed to fetch existing entry for check-out merge: {ex}")
        # --- END WORKAROUND ---

        # We don't execute it. We return a pending token.
        action_data = {
            "endpoint_id": endpoint_id,
            "method": method,
            "path": actual_path,
            "query_params": query_params,
            "body": body
        }
        
        # Generate encrypted token containing the action payload
        confirm_token = generate_confirmation_token(action_data, user_context["employeeId"])
        
        return json.dumps({
            "status": "pending_confirmation",
            "message": "This is a modifying action. Present this summary to the user and ask for confirmation.",
            "pending_confirmation_token": confirm_token,
            "action_summary": {
                "endpoint": endpoint_id,
                "path": actual_path,
                "payload": body
            }
        })

    # 3. Safe to execute GET requests
    settings = get_settings()
    url = f"{settings.java_backend_url}{actual_path}"
    
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            request_kwargs = {
                "url": url,
                "headers": headers,
                "params": query_params,
            }
            if body and method != "GET":
                request_kwargs["json"] = body
                
            response = await client.request(method, **request_kwargs)
            
            # Try to return JSON, otherwise text
            try:
                resp_data = response.json()
                return json.dumps({
                    "status_code": response.status_code,
                    "response": resp_data
                })
            except ValueError:
                return json.dumps({
                    "status_code": response.status_code,
                    "response": response.text
                })
                
    except Exception as e:
        logger.error(f"API call failed: {e}")
        return json.dumps({
            "error": str(e),
            "status": "failed"
        })
