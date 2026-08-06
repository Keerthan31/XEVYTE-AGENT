"""Xevyte HRMS AI Agent — LangGraph ReAct agent with OpenRouter LLM. Includes Enterprise Guardrails, Modular System Instructions, and Observability Tracing."""

import re
import logging
from typing import Annotated, TypedDict, Sequence
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from config import OPENAI_API_KEY, OPENAI_MODEL, FALLBACK_MODELS
from tools import ALL_TOOLS, set_session

logger = logging.getLogger(__name__)

# ─── MODULAR SYSTEM INSTRUCTIONS ──────────────────────────────────────────────
import os

# Load system prompt from external file to avoid IDE parsing issues
_prompt_path = os.path.join(os.path.dirname(__file__), "system_prompt.md")
with open(_prompt_path, "r", encoding="utf-8") as _f:
    SYSTEM_PROMPT = _f.read()


from guardrails import validate_guardrails, mask_pii, sanitize_output


# ─── ENTERPRISE GUARDRAILS ───────────────────────────────────────────────────
def check_prompt_guardrails(user_message: str) -> str | None:
    """Pre-inspect user input for prompt injection, jailbreak, or system leakage attempts. Returns a safety response if a violation is detected, else None."""
    inspection = validate_guardrails(user_message)
    if not inspection["safe"]:
        return inspection["reason"]
    return None


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]


def build_agent():
    llms_with_tools = []
    
    for model_name in FALLBACK_MODELS:
        llm = ChatOpenAI(
            model=model_name,
            api_key=OPENAI_API_KEY,
            temperature=0.0,
            max_retries=1,  # Fail fast to trigger fallback
            default_headers={
                "HTTP-Referer": "https://xevyte.com",
                "X-Title": "Xevyte HRMS Agent",
            },
        )
        llms_with_tools.append(llm.bind_tools(ALL_TOOLS))

    # The first model is primary, the rest are fallbacks
    llm_router = llms_with_tools[0].with_fallbacks(llms_with_tools[1:])

    def call_model(state: AgentState):
        response = llm_router.invoke(state["messages"])
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

    # Check enterprise guardrails first
    guardrail_response = check_prompt_guardrails(user_message)
    if guardrail_response:
        updated_history = history + [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": guardrail_response},
        ]
        return guardrail_response, updated_history

    set_session(token, employee_id)

    system = SystemMessage(
        content=SYSTEM_PROMPT.format(today=dt.today().isoformat(), employee_id=employee_id)
    )

    # Implement Session Memory: Keep only last 10 messages to prevent token overflow
    MAX_HISTORY = 10
    recent_history = history[-MAX_HISTORY:] if len(history) > MAX_HISTORY else history

    lc_messages: list[BaseMessage] = [system]
    for msg in recent_history:
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

    ai_reply = sanitize_output(ai_reply)

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

    # Check enterprise guardrails first
    guardrail_response = check_prompt_guardrails(user_message)
    if guardrail_response:
        yield guardrail_response
        return

    set_session(token, employee_id)

    system = SystemMessage(
        content=SYSTEM_PROMPT.format(today=dt.today().isoformat(), employee_id=employee_id)
    )

    # Implement Session Memory: Keep only last 10 messages
    MAX_HISTORY = 10
    recent_history = history[-MAX_HISTORY:] if len(history) > MAX_HISTORY else history

    lc_messages: list[BaseMessage] = [system]
    for msg in recent_history:
        if msg["role"] == "user":
            lc_messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            lc_messages.append(AIMessage(content=msg["content"]))
    lc_messages.append(HumanMessage(content=user_message))

    run_states = {}

    async for event in _compiled_agent.astream_events(
        {"messages": lc_messages}, config={"recursion_limit": 100}, version="v2"
    ):
        if event["event"] == "on_chat_model_stream":
            run_id = event["run_id"]
            if run_id not in run_states:
                run_states[run_id] = {"first_char_seen": False, "is_json_leak": False}

            state = run_states[run_id]
            chunk = event["data"]["chunk"]

            if chunk.tool_call_chunks:
                state["is_json_leak"] = True
                continue

            if isinstance(chunk.content, str) and chunk.content:
                text = chunk.content
                
                # Simple real-time streaming sanitizer to avoid leaking internal API URLs
                text = re.sub(r"https?://(?:localhost|127\.0\.0\.1|api\.xevyte\.local)(:\d+)?/api/[a-zA-Z0-9/\-_?=]+", "[INTERNAL_API_CALL]", text)

                if not state["first_char_seen"]:
                    if text.strip() == "":
                        continue
                    if text.lstrip().startswith("{"):
                        state["is_json_leak"] = True
                    state["first_char_seen"] = True

                if not state["is_json_leak"]:
                    yield text

        elif event["event"] == "on_tool_start":
            tool_name = event.get("name", "tool")
            yield f"__TOOL_START:{tool_name}__"

        elif event["event"] == "on_tool_end":
            yield "__TOOL_END__"
