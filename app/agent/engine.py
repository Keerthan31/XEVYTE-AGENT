import json
import logging
from typing import List, Dict, Any, Optional

from openai import AsyncOpenAI
import httpx

from app.config import get_settings
from app.agent.system_prompt import SYSTEM_PROMPT
from app.agent.tools import search_api_catalog, search_hr_knowledge_base, call_xevyte_api
from app.agent.confirmation import generate_confirmation_token

logger = logging.getLogger("xeva.agent.engine")

# Define the tools available to OpenAI
OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_api_catalog",
            "description": "Search the HRMS API catalog for endpoints matching a description",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (e.g., 'leave balance', 'submit expense')"
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
            "description": "Execute an API call to the Java HRMS backend. POST/PUT/DELETE calls will safely return a confirmation token.",
            "parameters": {
                "type": "object",
                "properties": {
                    "endpoint_id": {
                        "type": "string",
                        "description": "The exact ID of the endpoint from the catalog (e.g. 'submitEntry')"
                    },
                    "method": {
                        "type": "string",
                        "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                        "description": "HTTP method"
                    },
                    "path": {
                        "type": "string",
                        "description": "The URL path"
                    },
                    "path_params": {
                        "type": "object",
                        "description": "Parameters to substitute in the path template"
                    },
                    "query_params": {
                        "type": "object",
                        "description": "Query parameters"
                    },
                    "body": {
                        "type": "object",
                        "description": "JSON request body payload"
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
            "description": "Search HR policy documents for answers",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Question about policies (e.g., 'maternity leave duration')"
                    }
                },
                "required": ["query"]
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
    stalling_retries: Optional[int]

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

    tools = [
        search_api_catalog_tool,
        search_hr_knowledge_base_tool,
        call_xevyte_api_tool,
        analyze_document_from_url_tool,
        summarize_document_from_url_tool
    ]
    
    # 2. Build model
    model = ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.OPENAI_API_KEY,
        temperature=settings.LLM_TEMPERATURE,
        max_tokens=settings.LLM_MAX_TOKENS
    ).bind_tools(tools)
    
    # 3. Define Graph Nodes
    async def call_model_node(state: AgentState):
        import datetime
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        context_msg = f"Current Time: {current_time}\nUser Context: {json.dumps(state['user_context'])}"
        
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
        pending_token = None
        pending_actions = []
        
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
                    res_dict = json.loads(result)
                    if res_dict.get("status") == "pending_confirmation":
                        act = res_dict.get("action_data")
                        if act:
                            pending_actions.append(act)
                        elif res_dict.get("pending_confirmation_token"):
                            pending_token = res_dict.get("pending_confirmation_token")
                except Exception:
                    pass
            else:
                tool_outputs.append(ToolMessage(content=f"Error: Tool {tool_name} not found", tool_call_id=tool_call["id"]))
                
        if pending_actions:
            emp_id = user_context.get("employeeId", "unknown")
            if len(pending_actions) == 1:
                pending_token = generate_confirmation_token(pending_actions[0], emp_id)
            else:
                pending_token = generate_confirmation_token({"is_batch": True, "actions": pending_actions}, emp_id)
                
        return {"messages": tool_outputs, "pending_confirmation_token": pending_token}

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
            
        return END

    def route_after_tools(state: AgentState):
        if state.get("pending_confirmation_token"):
            return "confirm_node"
        return "agent"
        
    def confirm_node(state: AgentState):
        # Force a polite AIMessage so the UI shows it nicely
        return {"messages": [AIMessage(content="I have prepared the action. Please click the Approve button below to confirm.")]}

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
    workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", "nudge_tool_call": "nudge_node", END: END})
    workflow.add_conditional_edges("tools", route_after_tools, {"agent": "agent", "confirm_node": "confirm_node"})
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
                "pending_confirmation_token": None
            },
            {"recursion_limit": 10}
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
