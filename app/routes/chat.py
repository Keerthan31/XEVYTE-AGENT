import logging
import json
from typing import Dict, Any, List
import uuid
import httpx

from fastapi import APIRouter, Header, HTTPException, Depends
from pydantic import BaseModel

from app.auth.jwt_handler import validate_and_extract_token
from app.auth.guardrails import check_input_safety
from app.agent.engine import run_agent
from app.agent.confirmation import verify_confirmation_token
from app.config import get_settings
from app.db.database import get_db
from app.db.models import ChatMessage, ChatSession
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger("xeva.routes.chat")
router = APIRouter()

class ChatRequest(BaseModel):
    message: str
    session_id: str
    employee_id: str

class ConfirmRequest(BaseModel):
    token: str
    approve: bool
    session_id: str
    employee_id: str

@router.post("/chat")
async def chat_endpoint(
    request: ChatRequest,
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """Main chat endpoint"""
    # 1. Validate Auth
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
        
    user_context = validate_and_extract_token(authorization)
    if not user_context:
        raise HTTPException(status_code=401, detail="Invalid token")
        
    # Security check: Ensure employee_id matches token
    if request.employee_id != user_context["employeeId"]:
        raise HTTPException(status_code=403, detail="Employee ID mismatch")

    # 2. Guardrails check
    if not check_input_safety(request.message):
        return {
            "status": "success",
            "message": "I cannot fulfill this request as it violates safety guidelines.",
            "data": None
        }

    # 3. Load conversation history
    history = []
    if request.session_id:
        stmt = select(ChatMessage).where(ChatMessage.session_id == request.session_id).order_by(ChatMessage.created_at)
        result = await db.execute(stmt)
        messages = result.scalars().all()
        
        for msg in messages:
            if msg.role in ("user", "assistant"):
                history.append({"role": msg.role, "content": msg.content})

    # 4. Save user message to DB
    user_msg_db = ChatMessage(
        id=str(uuid.uuid4()),
        session_id=request.session_id,
        role="user",
        content=request.message
    )
    db.add(user_msg_db)
    await db.commit()

    # 5. Run Agent Engine
    token_str = authorization[7:] if authorization.startswith("Bearer ") else authorization
    
    agent_result = await run_agent(
        user_message=request.message,
        history=history,
        user_context=user_context,
        token=token_str
    )
    
    response_content = agent_result["content"]
    pending_token = agent_result.get("pending_confirmation_token")
    
    # 6. Save assistant message to DB
    assistant_msg_db = ChatMessage(
        id=str(uuid.uuid4()),
        session_id=request.session_id,
        role="assistant",
        content=response_content
    )
    db.add(assistant_msg_db)
    await db.commit()

    # 7. Return response
    return {
        "status": "success",
        "reply": response_content,
        "pending_confirmation_token": pending_token
    }

@router.post("/confirm")
async def confirm_endpoint(
    request: ConfirmRequest,
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """Endpoint for the frontend to approve or decline a pending action"""
    # 1. Validate Auth
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
        
    user_context = validate_and_extract_token(authorization)
    if not user_context:
        raise HTTPException(status_code=401, detail="Invalid token")

    if not request.approve:
        # User declined
        declined_msg = "Action cancelled by user."
        assistant_msg_db = ChatMessage(
            id=str(uuid.uuid4()),
            session_id=request.session_id,
            role="assistant",
            content=declined_msg
        )
        db.add(assistant_msg_db)
        await db.commit()
        return {"status": "success", "reply": declined_msg}

    # 2. Verify token
    try:
        action_data = verify_confirmation_token(request.token, user_context["employeeId"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 3. Execute the action
    settings = get_settings()
    
    path = action_data['path']
        
    url = f"{settings.java_backend_url}{path}"
    method = action_data["method"]
    
    token_str = authorization[7:] if authorization.startswith("Bearer ") else authorization
    headers = {
        "Authorization": f"Bearer {token_str}"
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            request_kwargs = {
                "url": url,
                "headers": headers,
                "params": action_data.get("query_params"),
            }
            if action_data.get("body"):
                if path == "/api/leaves/apply":
                    import json
                    request_kwargs["files"] = {"dto": (None, json.dumps(action_data["body"]), "application/json")}
                else:
                    headers["Content-Type"] = "application/json"
                    request_kwargs["json"] = action_data["body"]
                
            response = await client.request(method, **request_kwargs)
            
            try:
                resp_data = response.json()
            except:
                resp_data = response.text
                
            if response.is_success:
                success_msg = "Action completed successfully!"
            else:
                success_msg = f"Action failed with status {response.status_code}: {resp_data}"
                
            # 4. Save to DB
            assistant_msg_db = ChatMessage(
                id=str(uuid.uuid4()),
                session_id=request.session_id,
                role="assistant",
                content=success_msg
            )
            db.add(assistant_msg_db)
            await db.commit()
            
            return {
                "status": "success",
                "reply": success_msg,
                "data": resp_data
            }
            
    except Exception as e:
        logger.error(f"Execution failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to execute action")
