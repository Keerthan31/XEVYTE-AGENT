import logging
import json
from typing import Dict, Any, List
import uuid
import httpx

from fastapi import APIRouter, Header, HTTPException, Depends, UploadFile, File, Form
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

from langchain_core.messages import HumanMessage, AIMessage
from app.agent.memory import AsyncPostgresChatMessageHistory
from app.agent.file_parser import parse_file_for_agent

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

@router.post("/chat/upload")
async def chat_upload_endpoint(
    message: str = Form(...),
    session_id: str = Form(None),
    conversation_id: str = Form(None),
    employee_id: str = Form(...),
    files: UploadFile = File(...),
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """Chat endpoint that handles multipart file uploads."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
        
    user_context = validate_and_extract_token(authorization)
    if not user_context:
        raise HTTPException(status_code=401, detail="Invalid token")
        
    if employee_id != user_context["employeeId"]:
        raise HTTPException(status_code=403, detail="Employee ID mismatch")

    if not check_input_safety(message):
        return {
            "status": "success",
            "message": "I cannot fulfill this request as it violates safety guidelines.",
            "data": None
        }

    sid = session_id or conversation_id or str(uuid.uuid4())
    
    import os
    # Process the file and save to temp directory
    content = await files.read()
    file_context = parse_file_for_agent(files.filename, content, files.content_type)
    
    os.makedirs("/tmp/xevyte_uploads", exist_ok=True)
    temp_file_path = f"/tmp/xevyte_uploads/{uuid.uuid4()}_{files.filename}"
    with open(temp_file_path, "wb") as temp_file:
        temp_file.write(content)
    
    # Save the user message to DB
    user_msg_db = ChatMessage(
        id=str(uuid.uuid4()),
        session_id=sid,
        role="user",
        content=f"{message}\n\n[Attached file: {files.filename}]"
    )
    db.add(user_msg_db)
    await db.commit()

    # Pass everything to the agent engine
    history_obj = AsyncPostgresChatMessageHistory(session_id=sid, async_session=db)
    history_messages = await history_obj.aget_messages()
    history_dicts = [{"role": m.type, "content": m.content} for m in history_messages if m.type in ["human", "ai"]]

    result = await run_agent(message, history_dicts, user_context, authorization, file_context, temp_file_path)

    ai_content = result.get("output", "")
    assistant_msg_db = ChatMessage(
        id=str(uuid.uuid4()),
        session_id=sid,
        role="assistant",
        content=ai_content,
        pending_confirmation_token=result.get("pending_confirmation_token"),
        pending_action=result.get("pending_action")
    )
    db.add(assistant_msg_db)
    await db.commit()

    return {
        "status": "success",
        "reply": ai_content,
        "data": result.get("data")
    }

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

    # 3. Load conversation history via LangChain Memory
    history = []
    if request.session_id:
        # Initialize LangChain message history wrapper
        chat_memory = AsyncPostgresChatMessageHistory(session_id=request.session_id, db_session=db)
        
        # Save user message (this writes to DB seamlessly)
        await chat_memory.aadd_messages([HumanMessage(content=request.message)])
        
        # Load conversation history formatted for raw OpenAI SDK payload
        lc_messages = await chat_memory.aget_messages()
        
        for msg in lc_messages:
            if isinstance(msg, HumanMessage):
                history.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                history.append({"role": "assistant", "content": msg.content})

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
    
    # 6. Save assistant message to DB via LangChain Memory
    if request.session_id:
        await chat_memory.aadd_messages([AIMessage(content=response_content)])

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
        
    url = f"{settings.JAVA_BACKEND_URL}{path}"
    method = action_data["method"]
    
    token_str = authorization[7:] if authorization.startswith("Bearer ") else authorization
    headers = {
        "Authorization": f"Bearer {token_str}"
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            
            if action_data.get("endpoint_id") == "updateProfile":
                core_fields = ["contactNo", "emergencyContactNumber", "personalMail", "address", "presentAddress", "profilePic"]
                personal_fields = ["about", "whatILoveAboutMyJob", "interestsAndHobbies"]
                
                body = action_data.get("body", {})
                core_body = {k: v for k, v in body.items() if k in core_fields or k == "employeeId"}
                personal_body = {k: v for k, v in body.items() if k in personal_fields or k == "employeeId"}
                
                headers["Content-Type"] = "application/json"
                responses = []
                
                # Ensure employeeId is dynamically set just in case
                emp_id = user_context.get("employeeId")
                
                if any(k in core_fields for k in core_body.keys()):
                    core_url = f"{settings.JAVA_BACKEND_URL}/api/employees/{emp_id}"
                    core_resp = await client.put(core_url, headers=headers, json=core_body)
                    responses.append(core_resp)
                
                if any(k in personal_fields for k in personal_body.keys()):
                    personal_url = f"{settings.JAVA_BACKEND_URL}/api/employees/{emp_id}/personal-details"
                    personal_resp = await client.put(personal_url, headers=headers, json=personal_body)
                    responses.append(personal_resp)
                    
                is_success = all(r.is_success for r in responses) if responses else True
                resp_data = []
                for r in responses:
                    try:
                        resp_data.append(r.json())
                    except:
                        resp_data.append(r.text)
            else:
                request_kwargs = {
                    "url": url,
                    "headers": headers,
                    "params": action_data.get("query_params"),
                }
                if action_data.get("body"):
                    if path == "/api/leaves/apply":
                        import json
                        request_kwargs["files"] = {"dto": (None, json.dumps(action_data["body"]), "application/json")}
                    elif path == "/api/claims/submit":
                        import json
                        request_kwargs["files"] = {"claim": (None, json.dumps(action_data["body"]), "application/json")}
                        if action_data.get("temp_file_path") and os.path.exists(action_data["temp_file_path"]):
                            request_kwargs["files"]["receiptFile"] = open(action_data["temp_file_path"], "rb")
                    elif path == "/api/claims/draft":
                        import json
                        request_kwargs["files"] = {"claimDraft": (None, json.dumps(action_data["body"]), "application/json")}
                        if action_data.get("temp_file_path") and os.path.exists(action_data["temp_file_path"]):
                            request_kwargs["files"]["receiptFile"] = open(action_data["temp_file_path"], "rb")
                    elif path.startswith("/api/profile/update/"):
                        # Profile picture uses form-data instead of JSON string part
                        request_kwargs["data"] = {
                            "firstName": action_data["body"].get("firstName", "User"),
                            "lastName": action_data["body"].get("lastName", "")
                        }
                        if action_data.get("temp_file_path") and os.path.exists(action_data["temp_file_path"]):
                            request_kwargs["files"] = {"profilePic": open(action_data["temp_file_path"], "rb")}
                    else:
                        headers["Content-Type"] = "application/json"
                        request_kwargs["json"] = action_data["body"]
                    
                response = await client.request(method, **request_kwargs)
                is_success = response.is_success
                try:
                    resp_data = response.json()
                except:
                    resp_data = response.text
                
                # Cleanup temp file
                if action_data.get("temp_file_path") and os.path.exists(action_data["temp_file_path"]):
                    try:
                        os.remove(action_data["temp_file_path"])
                    except Exception as e:
                        print(f"Failed to clean up temp file: {e}")
                
            if is_success:
                success_msg = "Action completed successfully!"
            else:
                if isinstance(resp_data, dict):
                    err_msg = resp_data.get("message") or resp_data.get("error") or "Unknown error occurred"
                    success_msg = f"Action failed: {err_msg}"
                elif isinstance(resp_data, list) and len(resp_data) > 0 and isinstance(resp_data[0], dict):
                    err_msg = resp_data[0].get("message") or resp_data[0].get("error") or "Unknown error occurred"
                    success_msg = f"Action failed: {err_msg}"
                else:
                    success_msg = f"Action failed: {resp_data}"
                
            # 4. Save to DB
            assistant_msg_db = ChatMessage(
                id=str(uuid.uuid4()),
                session_id=request.session_id,
                role="assistant",
                content=success_msg
            )
            db.add(assistant_msg_db)
            await db.commit()
            
            # Cleanup temporary file
            if action_data.get("file_path") and os.path.exists(action_data["file_path"]):
                try:
                    os.remove(action_data["file_path"])
                except Exception as e:
                    logger.warning(f"Failed to delete temp file {action_data['file_path']}: {e}")
                    
            return {
                "status": "success",
                "reply": success_msg,
                "data": resp_data
            }
            
    except Exception as e:
        logger.error(f"Execution failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to execute action")
