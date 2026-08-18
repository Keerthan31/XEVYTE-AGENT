import json
import logging
from typing import List, Dict, Any, Optional

from openai import AsyncOpenAI
import httpx

from app.config import get_settings
from app.agent.system_prompt import SYSTEM_PROMPT
from app.agent.tools import search_api_catalog, search_hr_knowledge_base, call_xevyte_api

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
                "required": ["endpoint_id", "method", "path"]
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

async def run_agent(
    user_message: str, 
    history: List[Dict[str, str]], 
    user_context: Dict[str, Any],
    token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Main ReAct loop using OpenAI's function calling.
    Returns a dict with 'content' and possibly 'pending_confirmation_token'.
    """
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    
    # 1. Build message history
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    import datetime
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Add user context as a system message
    context_msg = f"Current Time: {current_time}\nUser Context: {json.dumps(user_context)}"
    messages.append({"role": "system", "content": context_msg})
    
    # Add history
    messages.extend(history)
    
    # Add current message
    messages.append({"role": "user", "content": user_message})
    
    # Maximum loops to prevent infinite recursion
    max_loops = 5
    current_loop = 0
    
    pending_token = None
    
    while current_loop < max_loops:
        current_loop += 1
        
        try:
            # 2. Call OpenAI
            response = await client.chat.completions.create(
                model=settings.llm_model,
                messages=messages,
                tools=OPENAI_TOOLS,
                tool_choice="auto",
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_tokens
            )
            
            response_message = response.choices[0].message
            messages.append(response_message)
            
            # 3. If no tool calls, we're done
            if not response_message.tool_calls:
                return {
                    "content": response_message.content,
                    "pending_confirmation_token": pending_token
                }
                
            # 4. Execute tool calls
            for tool_call in response_message.tool_calls:
                tool_name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                    
                tool_result = ""
                
                logger.info(f"Executing tool: {tool_name} with args: {args}")
                
                if tool_name == "search_api_catalog":
                    tool_result = search_api_catalog(args.get("query", ""))
                    
                elif tool_name == "search_hr_knowledge_base":
                    tool_result = search_hr_knowledge_base(args.get("query", ""))
                    
                elif tool_name == "call_xevyte_api":
                    tool_result = await call_xevyte_api(
                        endpoint_id=args.get("endpoint_id"),
                        method=args.get("method"),
                        path=args.get("path"),
                        user_context=user_context,
                        path_params=args.get("path_params"),
                        query_params=args.get("query_params"),
                        body=args.get("body"),
                        token=token
                    )
                    
                    # Intercept pending confirmation
                    try:
                        result_dict = json.loads(tool_result)
                        if result_dict.get("status") == "pending_confirmation":
                            pending_token = result_dict.get("pending_confirmation_token")
                    except Exception:
                        pass
                else:
                    tool_result = f"Error: Tool {tool_name} not found"
                    
                # Append tool result to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": str(tool_result)
                })
                
        except Exception as e:
            logger.error(f"Agent engine error: {e}")
            return {
                "content": f"I encountered an error while processing your request: {str(e)}",
                "pending_confirmation_token": None
            }
            
    return {
        "content": "I apologize, but I reached the maximum number of steps without completing the task. Please try rephrasing your request.",
        "pending_confirmation_token": pending_token
    }
