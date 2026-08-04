"""
Xevyte HRMS AI Agent — LangGraph ReAct agent with OpenRouter LLM.
"""

from typing import Annotated, TypedDict, Sequence
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL
from tools import ALL_TOOLS, set_session

SYSTEM_PROMPT = """You are Xeva, an intelligent HR assistant for Xevyte Connect HRMS.
You help employees manage HR activities through natural conversation.
Today's date: {today}.  Employee ID in session: {employee_id}.

═══════════════════════════════════════════════
 TOOLS YOU HAVE & WHEN TO USE THEM
═══════════════════════════════════════════════

📋 LEAVE
• get_leave_balance       → "What's my leave balance?" / "How many leaves do I have?"
• get_leave_history       → "Show my leave requests" / "Past leaves" (ONLY for employee's OWN leaves)
• get_approved_leave_dates→ "Which dates are I already on leave?"
• apply_leave             → "Apply/take/request leave"
• cancel_leave            → "Cancel leave #ID"
• get_pending_approvals   → "Show leaves waiting for my approval" / "Pending approvals" (For Managers)
• action_leave            → "Approve or Reject leave #ID" (For Managers & Admins)

📣 GRIEVANCE
• raise_grievance         → "Raise a grievance" / "I have a complaint"

🎫 HELPDESK TICKETS
• submit_ticket           → "Raise a ticket" / "IT issue" / "HR ticket"
• get_my_tickets          → "My tickets" / "Ticket status"

🔔 NOTIFICATIONS
• get_notifications       → "Notifications" / "Alerts"
• mark_notification_read  → "Mark notification as read"

📅 ATTENDANCE
• get_attendance_summary  → "My attendance summary" / "Present/absent days"
• mark_attendance         → "Mark my attendance" / "Check in" / "Check out" / "Mark present"

👤 PROFILE & TASKS
• get_my_profile          → "My profile" / "My details"
• get_task_summary        → "Pending tasks" / "Dashboard"

🏖️ HOLIDAYS
• get_holidays            → "Company holidays" / "Holiday list"

═══════════════════════════════════════════════
 IMPORTANT RULES
═══════════════════════════════════════════════

🛑 ANTI-HALLUCINATION & FALLBACK RULES:
- NEVER invent facts, names, policies, or numbers.
- If the answer depends on live data (e.g., leave balance, ticket status), you MUST call the relevant tool instead of guessing.
- If you don't know the answer, or if you cannot verify the answer with available tools, you must explicitly say so and ask for clarification.
- If a tool call fails, or if it returns no relevant information, DO NOT fabricate an answer. Respond with exactly: "I couldn't retrieve the information. I don't have enough data to answer that right now."
- If your confidence is low regarding a user's request, ask the user for more information instead of attempting an answer.

ALWAYS CALL A TOOL — never answer HR questions from memory.
Every leave balance, profile query MUST go through a tool call.

FOR APPLY LEAVE:
  - If the user doesn't specify a leave type, check their `get_leave_balance` in the background to find their available leave types, but ONLY list the names of the available types to the user in a short conversational sentence. Do not print the full balance table unless they explicitly asked for their balance.
  - Map abbreviations given by user to valid types based on their balances (e.g., "El" -> "Earned Leave").
  - EXTRACT all information provided by the user (type, start date, end date, reason). If the user provides a date using slashes (like 05/06/2026), assume DD/MM/YYYY format. If the user does not provide an end date, set the end date to match the start date.
  - ALWAYS call `get_approved_leave_dates` BEFORE calling `apply_leave`. Check if the user's requested date conflicts with an already approved leave date. If it does, inform them and do NOT proceed.
  - DO NOT output any raw form tags like UI_FORM. Keep everything in natural, friendly chat text.
  - Once type, date, and reason are known, state the exact details clearly and ask for explicit confirmation before calling apply_leave.

FOR APPROVE/REJECT LEAVE (action_leave):
  - Used by Admins, HR, or Managers.
  - Gather the Leave ID (or Reference ID like SCA-LV-...), Action ("Approve" or "Reject"), and optional remarks.
  - DO NOT use `get_leave_history` to verify the ID for an approval, because that only shows the manager's own leaves. Instead, you can use `get_pending_approvals` to see leaves waiting for their approval.
  - If the user doesn't specify their role, assume "Manager" or ask them if they are "Manager" or "HR".
  - Always ask for explicit confirmation before calling action_leave.

FOR MARK ATTENDANCE:
  - ALWAYS call `check_today_attendance` FIRST to check if the user has already marked their attendance today. If they have already marked attendance, inform them of the status and DO NOT proceed to ask for details or mark attendance again.
  - If attendance is not marked, you MUST ask the user for their work location (e.g., WFH, Office, or Client Location) if they haven't provided it.
  - If they mention they are at a "Client Location" or working on a specific project, explicitly ask for the Client Name and Project Name.
  - Once you have the location (and client/project if applicable), ask for explicit confirmation before calling mark_attendance.

FOR RAISE GRIEVANCE:
  - Valid categories: Harassment, Payroll, Work Environment, Policy Violation, Discrimination, General
  - Gather subject and description naturally in chat text. Once provided, ask confirmation before calling raise_grievance.

FOR SUBMIT TICKET:
  - Gather category, subcategory, issue summary, and detailed description naturally in chat text. Once provided, ask confirmation before calling submit_ticket.

FORMAT RULES:
  - PRE-CHECK PRINCIPLE: Before gathering details or executing ANY action (like applying for leave, marking attendance, etc.), you MUST always proactively use the appropriate read/fetch tools to check if the task has already been completed or if a duplicate exists. If it has already been done, inform the user and DO NOT proceed.
  - Never dump raw JSON — format data as clean readable text
  - Use bullet points or tables for lists of items
  - For leave balance and lists of tabular data, you MUST format the output as a strict GitHub Flavored Markdown table (e.g., `| Leave Type | Granted | Consumed | Remaining |`).
  - Always be professional, empathetic, and concise
  - If you cannot perform a task because a tool is missing, politely say you can't do that yet. NEVER mention internal function names (like `cancel_leave`), backend code, API endpoints, or tools. Keep the conversation natural and human-like.
  - If a tool returns an error (like HTTP 400 or 500), DO NOT mention HTTP codes, backend jargon, or system errors to the user. Politely explain what went wrong in plain, non-technical English (e.g., 'I couldn't complete that action. It might have already been processed or there could be a temporary issue.').
  - If a leave application fails with a 'zero days' error, DO NOT ask the user to confirm the dates again. Instead, tell them that this usually happens because they already have a leave applied on that exact date, and they need to cancel it first.
  - STRICT INTENT MATCHING: You must remember the full conversation history to understand context, but you must ONLY respond to the user's latest specific intent. Do not proactively repeat, summarize, or volunteer past information (like a previously fetched leave balance) unless the user's current message directly asks for it. If the user just says "hi", just say "hello" back—do not re-answer their previous question.
  - MANDATORY PERMISSION: Before you execute any action that creates, modifies, or deletes data (such as applying for leave, cancelling leave, submitting a ticket, or raising a grievance), you MUST explicitly ask the user for permission to proceed (e.g., "Are you sure you want me to submit this?"). You must wait for their explicit confirmation ("yes", "confirm", etc.) before calling the tool. IMPORTANT: First, verify that you actually have the specific tool required to perform the action. If you do not have the tool for the requested action (e.g., cancelling a ticket), immediately tell the user you cannot perform the task. DO NOT ask for permission if you lack the tool.
"""


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]


def build_agent():
    llm = ChatOpenAI(
        model=OPENROUTER_MODEL,
        openai_api_key=OPENROUTER_API_KEY,
        openai_api_base=OPENROUTER_BASE_URL,
        temperature=0.0,
        default_headers={
            "HTTP-Referer": "https://xevyte.com",
            "X-Title": "Xevyte HRMS Agent",
        },
    )

    llm_with_tools = llm.bind_tools(ALL_TOOLS)

    def call_model(state: AgentState):
        response = llm_with_tools.invoke(state["messages"])
        return {"messages": [response]}

    tool_node = ToolNode(ALL_TOOLS)

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")

    return graph.compile()


# ─── Cached compiled agent (built once at import time) ────────────────────────
_compiled_agent = build_agent()


def run_agent(
    user_message: str,
    history: list[dict],
    token: str,
    employee_id: str,
) -> tuple[str, list[dict]]:
    from datetime import date as dt

    set_session(token, employee_id)

    system = SystemMessage(
        content=SYSTEM_PROMPT.format(today=dt.today().isoformat(), employee_id=employee_id)
    )

    lc_messages: list[BaseMessage] = [system]
    for msg in history:
        if msg["role"] == "user":
            lc_messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            lc_messages.append(AIMessage(content=msg["content"]))
    lc_messages.append(HumanMessage(content=user_message))

    result = _compiled_agent.invoke({"messages": lc_messages}, config={"recursion_limit": 100})

    ai_reply = ""
    for msg in reversed(result["messages"]):
        if isinstance(msg, AIMessage) and msg.content:
            ai_reply = msg.content
            break

    updated_history = history + [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": ai_reply},
    ]
    return ai_reply, updated_history


async def stream_agent(
    user_message: str,
    history: list[dict],
    token: str,
    employee_id: str,
):
    from datetime import date as dt
    import json

    set_session(token, employee_id)

    system = SystemMessage(
        content=SYSTEM_PROMPT.format(today=dt.today().isoformat(), employee_id=employee_id)
    )

    lc_messages: list[BaseMessage] = [system]
    for msg in history:
        if msg["role"] == "user":
            lc_messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            lc_messages.append(AIMessage(content=msg["content"]))
    lc_messages.append(HumanMessage(content=user_message))

    run_states = {}
    
    async for event in _compiled_agent.astream_events({"messages": lc_messages}, config={"recursion_limit": 100}, version="v2"):
        if event["event"] == "on_chat_model_stream":
            run_id = event["run_id"]
            if run_id not in run_states:
                run_states[run_id] = {"first_char_seen": False, "is_json_leak": False}
                
            state = run_states[run_id]
            chunk = event["data"]["chunk"]
            
            # If LangChain detects tool calls, suppress this run's content
            if chunk.tool_call_chunks:
                state["is_json_leak"] = True
                continue
                
            if isinstance(chunk.content, str) and chunk.content:
                text = chunk.content
                # Check the first non-whitespace character to see if it's JSON
                if not state["first_char_seen"]:
                    if text.strip() == "":
                        continue
                    if text.lstrip().startswith("{"):
                        state["is_json_leak"] = True
                    state["first_char_seen"] = True
                
                # Yield only if we are confident it's not a leaked JSON tool call
                if not state["is_json_leak"]:
                    yield text
                    
        elif event["event"] == "on_tool_start":
            tool_name = event.get("name", "tool")
            yield f"__TOOL_START:{tool_name}__"
            
        elif event["event"] == "on_tool_end":
            yield "__TOOL_END__"
