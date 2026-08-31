import json
import logging
from typing import List, Dict, Any, Optional

from openai import AsyncOpenAI
import httpx

from app.config import get_settings
from app.agent.system_prompt import SYSTEM_PROMPT
from app.agent.tools import (
    search_api_catalog, 
    search_hr_knowledge_base, 
    call_xevyte_api, 
    prepare_batch_approvals,
    ask_clarification
)
from app.agent.confirmation import generate_confirmation_token, verify_confirmation_token

logger = logging.getLogger("xeva.agent.engine")

# Define the tools available to OpenAI
OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_api_catalog",
            "description": "Search the HRMS API catalog for endpoints matching a user's intent. ALWAYS search the catalog if you don't know the exact endpoint_id or its required schema.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (e.g., 'leave balance', 'submit expense', 'view org chart')"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "call_xevyte_api",
            "description": "Execute an API call to the Java HRMS backend. POST/PUT/DELETE calls will safely return a confirmation token. NEVER guess missing IDs or fields.",
            "parameters": {
                "type": "object",
                "properties": {
                    "endpoint_id": {
                        "type": "string",
                        "description": "The exact ID of the endpoint from the catalog (e.g. 'submitEntry', 'applyLeave', 'getDetailedLeaveBalance')"
                    },
                    "method": {
                        "type": "string",
                        "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                        "description": "HTTP method (auto-resolved if omitted)"
                    },
                    "path": {
                        "type": "string",
                        "description": "The URL path (auto-resolved if omitted)"
                    },
                    "path_params": {
                        "type": "object",
                        "description": "Parameters to substitute in the path template (e.g. {'id': 10})"
                    },
                    "query_params": {
                        "type": "object",
                        "description": "Query parameters for GET requests (e.g. {'startDate': '2026-08-01'})"
                    },
                    "body": {
                        "type": "object",
                        "description": "JSON request body payload matching exactly the required/optional schema from the tool description. NEVER hallucinate fields."
                    }
                },
                "required": ["endpoint_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_hr_knowledge_base",
            "description": "Search official HR policy documents, handbook, and guidelines. Use whenever the user asks about leave policies, working hours, probation, or company rules.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Question about policies (e.g., 'probation period policy', 'paternity leave rules')"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ask_clarification",
            "description": "FALLBACK TOOL: Explicitly ask the user for clarification when their request is ambiguous, confusing, lacks required input details, or no tool in the catalog matches their intent. NEVER guess or make up data when you can ask.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The clear, friendly clarification question to ask the user"
                    },
                    "reason": {
                        "type": "string",
                        "description": "The internal reason why clarification is needed (e.g., 'missing leave type and dates')"
                    }
                },
                "required": ["question"]
            }
        }
    }
]

from typing import Annotated, TypedDict, List, Dict, Any, Optional
from langchain_core.messages import BaseMessage, AIMessage, ToolMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

import re

STALLING_PATTERNS = [
    r"please\s+(?:hold\s+on|wait|give\s+me)",
    r"hold\s+on\s+(?:a\s+moment|for\s+a\s+moment|sec|second|please)",
    r"let\s+me\s+(?:first\s+)?(?:check|retrieve|fetch|look|find|pull)",
    r"retriev(?:e|ing)\s+(?:that|your|the)\s+information",
    r"fetching\s+(?:that|your|the)\s+information",
    r"looking\s+into\s+(?:that|your|this)",
    r"just\s+a\s+moment",
    r"give\s+me\s+a\s+moment",
    r"searching\s+(?:the\s+catalog|for\s+the|the\s+database)",
]

def is_stalling_response(content: str) -> bool:
    if not content or not isinstance(content, str):
        return False
    lower = content.lower().strip()
    return any(re.search(pat, lower) for pat in STALLING_PATTERNS)

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    user_context: Dict[str, Any]
    token: Optional[str]
    pending_confirmation_token: Optional[str]
    pending_actions: Optional[List[Dict[str, Any]]]
    stalling_retries: Optional[int]

def format_action_summary(action_data: Optional[Dict[str, Any]]) -> str:
    """
    Builds a user-friendly Markdown summary table of the prepared action
    so the user knows exactly what parameters are being executed before confirming.
    """
    if not action_data:
        return "I have prepared the action. Please click the Approve button below to confirm."

    if action_data.get("is_batch"):
        actions = action_data.get("actions", [])
        if not actions:
            return "I have prepared the actions. Please click the Approve button below to confirm."
        summaries = [format_action_summary(a) for a in actions]
        return "\n\n---\n\n".join(summaries)

    endpoint_id = action_data.get("endpoint_id", "")
    body = action_data.get("body") or {}
    path = action_data.get("path", "")
    query_params = action_data.get("query_params") or {}
    path_params = action_data.get("path_params") or {}

    # Action title mappings
    action_titles = {
        "applyLeave": "Apply Leave",
        "cancelLeave": "Cancel Leave",
        "submitClaim": "Submit Expense Claim",
        "saveDraft": "Save Expense Claim Draft",
        "cancelClaim": "Cancel Expense Claim",
        "createRequest": "Create Travel Request",
        "submitTicket": "Submit Support Ticket",
        "submitChangeRequest": "Submit Change Request",
        "fileGrievance": "Submit Anonymous Grievance",
        "createCustomer": "Register New Customer",
        "updateCustomer": "Update Customer",
        "createSow": "Create Statement of Work (SOW)",
        "createProject": "Create Project",
        "createApplicant": "Create Applicant Profile",
        "onboardSingleEmployee": "Onboard Employee",
        "bulkOnboardEmployees": "Bulk Onboard Employees",
        "createAsset": "Add Asset to Inventory",
        "allocateAsset": "Allocate Asset",
        "returnAssetAllocation": "Return Asset",
        "approveLeave": "Approve Leave Request",
        "rejectLeave": "Reject Leave Request",
        "approveClaim": "Approve Expense Claim",
        "rejectClaim": "Reject Expense Claim",
        "approveRequest": "Approve Travel Request",
        "rejectRequest": "Reject Travel Request",
        "managerApproveTicket": "Approve Ticket",
        "managerRejectTicket": "Reject Ticket",
        "submitResignation": "Submit Resignation",
        "saveOrUpdate": "Submit IT Tax Declaration",
        "reopenTicket": "Reopen Support Ticket",
        "cancelTicket": "Cancel Support Ticket",
    }

    title = action_titles.get(endpoint_id)
    if not title:
        if "leave" in path.lower():
            title = "Apply Leave"
        elif "claim" in path.lower():
            title = "Expense Claim"
        elif "travel" in path.lower():
            title = "Travel Request"
        elif "ticket" in path.lower():
            title = "Support Ticket"
        elif "asset" in path.lower():
            title = "Asset Request"
        else:
            title = endpoint_id or "Action Request"

    # Merge non-empty fields from body, path_params, and query_params
    combined_params: Dict[str, Any] = {}
    if isinstance(body, dict):
        combined_params.update(body)
    if isinstance(query_params, dict):
        combined_params.update(query_params)
    if isinstance(path_params, dict):
        combined_params.update(path_params)

    # Human-friendly field name mappings
    field_labels = {
        "type": "Leave Type",
        "leaveType": "Leave Type",
        "leave_type": "Leave Type",
        "startDate": "Start Date",
        "fromDate": "From Date",
        "start_date": "Start Date",
        "endDate": "End Date",
        "toDate": "To Date",
        "end_date": "End Date",
        "numberOfDays": "Number of Days",
        "days": "Number of Days",
        "reason": "Reason",
        "remarks": "Remarks",
        "comments": "Comments",
        "amount": "Amount",
        "category": "Category",
        "subcategory": "Subcategory",
        "subCategory": "Subcategory",
        "expenseDate": "Expense Date",
        "expenseDescription": "Description",
        "fromLocation": "From Location",
        "toLocation": "To Location",
        "modeOfTravel": "Mode of Travel",
        "mode": "Mode of Travel",
        "departureDate": "Departure Date",
        "returnDate": "Return Date",
        "purposeOfTravel": "Purpose",
        "purpose": "Purpose",
        "issueSummary": "Summary",
        "detailedDescription": "Detailed Description",
        "customerName": "Customer Name",
        "projectName": "Project Name",
        "sowName": "SOW Name",
        "firstName": "First Name",
        "lastName": "Last Name",
        "designation": "Designation",
        "lastWorkingDay": "Last Working Day",
        "reasonForExit": "Reason for Exit",
        "financialYear": "Financial Year",
        "taxRegime": "Tax Regime",
        "leaveRequestId": "Leave Request ID",
        "ticketId": "Ticket ID",
        "requestId": "Request ID",
        "claimId": "Claim ID",
        "id": "Record ID"
    }

    # Exclude internal technical parameters
    excluded_keys = {
        "employeeId", "tenantId", "frozen", "loginTime", "status", "temp_file_path",
        "role", "action", "applicantId", "clientId", "projectId"
    }

    rows = []
    rows.append(f"| **Action** | {title} |")
    for k, v in combined_params.items():
        if k in excluded_keys or v is None or v == "" or v == {}:
            continue
        label = field_labels.get(k, k.replace("_", " ").title())
        val_str = str(v)
        rows.append(f"| **{label}** | {val_str} |")

    table_content = "| Field | Value |\n| :--- | :--- |\n" + "\n".join(rows) + "\n\n"

    msg = (
        f"I have prepared the action. Please review the details below:\n\n"
        f"{table_content}"
        f"Please click the **Approve** button below to confirm."
    )
    return msg

async def run_agent(
    user_message: str, 
    history: List[Dict[str, str]], 
    user_context: Dict[str, Any],
    token: Optional[str] = None,
    file_context: Optional[Dict[str, Any]] = None,
    temp_file_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Main LangGraph loop using ChatOpenAI.
    """
    settings = get_settings()
    
    if temp_file_path:
        user_context["temp_file_path"] = temp_file_path
    
    # 1. Define Tools dynamically so we can close over user_context and token
    @tool
    def search_api_catalog_tool(query: str) -> str:
        """Search the HRMS API catalog for endpoints matching a description."""
        return search_api_catalog(query)

    @tool
    def search_hr_knowledge_base_tool(query: str) -> str:
        """Search HR policy documents for answers."""
        return search_hr_knowledge_base(query)

    @tool
    async def call_xevyte_api_tool(
        endpoint_id: str,
        method: Optional[str] = None,
        path: Optional[str] = None,
        path_params: Optional[Dict[str, Any]] = None,
        query_params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None
    ) -> str:
        """Execute an API call to the Java HRMS backend. POST/PUT/DELETE calls will safely return a confirmation token."""
        result = await call_xevyte_api(
            endpoint_id=endpoint_id,
            method=method,
            path=path,
            user_context=user_context,
            path_params=path_params,
            query_params=query_params,
            body=body,
            token=token
        )
        return json.dumps(result) if isinstance(result, dict) else str(result)

    @tool
    async def analyze_document_from_url_tool(document_url_or_path: str, question: str) -> str:
        """Stream any PDF, DOCX, XLSX, or Receipt from Java HRMS into RAM and answer questions with exact figures and page citations without saving files to disk."""
        from app.rag.doc_rag import answer_question_from_document_stream
        result = await answer_question_from_document_stream(document_url_or_path, question, token)
        return json.dumps(result) if isinstance(result, dict) else str(result)

    @tool
    async def summarize_document_from_url_tool(document_url_or_path: str, focus_area: Optional[str] = None) -> str:
        """Stream any document from Java HRMS into RAM and produce a structured executive summary."""
        from app.rag.doc_rag import summarize_document_from_stream
        result = await summarize_document_from_stream(document_url_or_path, focus_area, token)
        return json.dumps(result) if isinstance(result, dict) else str(result)

    @tool
    async def batch_approve_reject_tasks_tool(
        actions: List[Dict[str, Any]]
    ) -> str:
        """Approve or reject multiple pending workflow tasks (Leaves, Claims, Travel, Exit/Resignation) in a single batch.
        actions: A list of dicts where each dict must have keys: 'task_id' (e.g. 26 or 'LV-26'), 'type' (e.g. 'Leave Approval'), 'action' (e.g. 'Approve' or 'Reject'), and optional 'comment' / 'reason' / 'comments' (remarks for rejection)."""
        result = await prepare_batch_approvals(actions, user_context, token)
        return json.dumps(result)

    @tool
    def ask_clarification_tool(question: str, reason: Optional[str] = None) -> str:
        """FALLBACK / ANTI-HALLUCINATION TOOL: Ask the user a clarifying question when their intent is ambiguous, required parameters are missing, or no API tool fits the request. NEVER guess or make up data when you can ask."""
        result = ask_clarification(question, reason)
        return json.dumps(result)

    tools = [
        search_api_catalog_tool,
        search_hr_knowledge_base_tool,
        call_xevyte_api_tool,
        analyze_document_from_url_tool,
        summarize_document_from_url_tool,
        batch_approve_reject_tasks_tool,
        ask_clarification_tool
    ]
    
    # 2. Build model with deterministic temperature (0.0) to prevent hallucinations
    model = ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.OPENAI_API_KEY,
        temperature=0.0,
        max_tokens=settings.LLM_MAX_TOKENS
    ).bind_tools(tools)
    
    # 3. Define Graph Nodes
    async def call_model_node(state: AgentState):
        import datetime
        now = datetime.datetime.now()
        current_time = now.strftime("%Y-%m-%d %H:%M:%S")
        day_name = now.strftime("%A")
        context_msg = f"Current Time: {current_time} (Today is {day_name})\nUser Context: {json.dumps(state['user_context'])}"
        
        # Inject system prompt and context if not already there
        from langchain_core.messages import SystemMessage
        messages = state["messages"]
        if not any(isinstance(m, SystemMessage) for m in messages):
            messages = [SystemMessage(content=SYSTEM_PROMPT), SystemMessage(content=context_msg)] + messages
            
        response = await model.ainvoke(messages)
        return {"messages": [response]}
        
    async def call_tools_node(state: AgentState):
        messages = state["messages"]
        last_message = messages[-1]
        
        tool_outputs = []
        # Accumulate pending actions across multiple turns (for batch approvals)
        accumulated_actions = list(state.get("pending_actions") or [])
        
        tool_map = {t.name: t for t in tools}
        
        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_instance = tool_map.get(tool_name)
            
            if tool_instance:
                result = await tool_instance.ainvoke(tool_args)
                tool_outputs.append(ToolMessage(content=result, tool_call_id=tool_call["id"]))
                
                # Intercept pending confirmation for any tool that returns it
                try:
                    res_dict = result if isinstance(result, dict) else json.loads(result)
                    if res_dict.get("status") == "pending_confirmation":
                        if "batch_actions" in res_dict:
                            accumulated_actions.extend(res_dict["batch_actions"])
                        else:
                            act = res_dict.get("action_data")
                            if act:
                                accumulated_actions.append(act)
                except Exception as e:
                    logger.error(f"Error parsing tool output: {e}")
                    pass
            else:
                tool_outputs.append(ToolMessage(content=f"Error: Tool {tool_name} not found", tool_call_id=tool_call["id"]))
        
        # Store accumulated actions in state — do NOT create the token yet.
        # The token is created in confirm_node after the LLM finishes all its calls.
        return {"messages": tool_outputs, "pending_actions": accumulated_actions}

    # 4. Define Graph Routing
    def should_continue(state: AgentState):
        messages = state["messages"]
        last_message = messages[-1]
        if getattr(last_message, "tool_calls", None):
            return "tools"
            
        # Programmatic Guard: If model returned stalling text without calling tools, auto-nudge it
        retries = state.get("stalling_retries", 0) or 0
        if retries < 2 and isinstance(last_message, AIMessage) and is_stalling_response(last_message.content):
            logger.info(f"Engine caught stalling text without tool calls: {repr(last_message.content[:80])}. Nudging model to execute tool.")
            return "nudge_tool_call"
        
        # If the LLM stopped calling tools AND there are pending actions,
        # finalize them into a batch confirmation token.
        if state.get("pending_actions"):
            return "confirm_node"
            
        return END

    def route_after_tools(state: AgentState):
        # ALWAYS return to agent so the LLM can make more tool calls
        # (e.g. for batch approvals). The graph only stops when the LLM
        # decides to output text (no more tool_calls), at which point
        # should_continue routes to confirm_node if there are pending actions.
        return "agent"
        
    def confirm_node(state: AgentState):
        # Create the batch confirmation token from all accumulated pending actions
        accumulated_actions = state.get("pending_actions") or []
        emp_id = state.get("user_context", {}).get("employeeId", "unknown")
        
        if accumulated_actions:
            if len(accumulated_actions) == 1:
                pending_token = generate_confirmation_token(accumulated_actions[0], emp_id)
            else:
                pending_token = generate_confirmation_token({"is_batch": True, "actions": accumulated_actions}, emp_id)
            
            # Verify to build the summary
            try:
                action_data = verify_confirmation_token(pending_token, emp_id)
            except Exception as e:
                logger.warning(f"Could not verify confirmation token for summary formatting: {e}")
                action_data = None
            
            summary_text = format_action_summary(action_data)
            return {"messages": [AIMessage(content=summary_text)], "pending_confirmation_token": pending_token, "pending_actions": []}
        
        # Fallback: legacy path with pre-existing token
        token = state.get("pending_confirmation_token")
        action_data = None
        if token:
            try:
                action_data = verify_confirmation_token(token, emp_id)
            except Exception as e:
                logger.warning(f"Could not verify confirmation token for summary formatting: {e}")
        
        summary_text = format_action_summary(action_data)
        return {"messages": [AIMessage(content=summary_text)]}

    def nudge_node(state: AgentState):
        retries = (state.get("stalling_retries", 0) or 0) + 1
        nudge_msg = HumanMessage(
            content="[SYSTEM NOTICE: Do not output conversational holding text like 'Please hold on...'. You must immediately call the required tool (call_xevyte_api or search_api_catalog) right now in your response to complete the user's request.]"
        )
        return {"messages": [nudge_msg], "stalling_retries": retries}

    # 5. Build Graph
    workflow = StateGraph(AgentState)
    workflow.add_node("agent", call_model_node)
    workflow.add_node("tools", call_tools_node)
    workflow.add_node("confirm_node", confirm_node)
    workflow.add_node("nudge_node", nudge_node)
    
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", "nudge_tool_call": "nudge_node", "confirm_node": "confirm_node", END: END})
    workflow.add_conditional_edges("tools", route_after_tools, {"agent": "agent"})
    workflow.add_edge("confirm_node", END)
    workflow.add_edge("nudge_node", "agent")
    
    app = workflow.compile()
    
    # 6. Execute Graph
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
    
    # Reconstruct history
    lc_messages = []
    
    for h in history:
        if h["role"] == "user":
            lc_messages.append(HumanMessage(content=h["content"]))
        elif h["role"] == "assistant":
            lc_messages.append(AIMessage(content=h["content"]))

    # Inject file context if provided by replacing the last user message
    if file_context and len(lc_messages) > 1 and isinstance(lc_messages[-1], HumanMessage):
        last_msg = lc_messages.pop()
        
        if file_context["type"] == "image":
            msg_content = [
                {"type": "text", "text": last_msg.content},
                {"type": "image_url", "image_url": {"url": file_context["data"]}}
            ]
            lc_messages.append(HumanMessage(content=msg_content))
        elif file_context["type"] == "document":
            combined_message = f"{last_msg.content}\n\n[Content of attached file '{file_context['filename']}']\n\n{file_context['data']}"
            lc_messages.append(HumanMessage(content=combined_message))
    
    from langgraph.errors import GraphRecursionError
    
    try:
        final_state = await app.ainvoke(
            {
                "messages": lc_messages, 
                "user_context": user_context, 
                "token": token,
                "pending_confirmation_token": None,
                "pending_actions": []
            },
            {"recursion_limit": 25}
        )
        
        final_message = final_state["messages"][-1]
        
        return {
            "content": final_message.content,
            "pending_confirmation_token": final_state.get("pending_confirmation_token")
        }
    except GraphRecursionError:
        logger.error("Agent hit recursion limit")
        return {
            "content": "I apologize, but I reached the maximum number of steps without completing the task. Please try rephrasing your request.",
            "pending_confirmation_token": None
        }
    except Exception as e:
        logger.error(f"Agent engine error: {e}")
        return {
            "content": f"I encountered an error while processing your request: {str(e)}",
            "pending_confirmation_token": None
        }
