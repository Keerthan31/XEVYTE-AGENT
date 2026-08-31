import logging
import json
import os
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
        
    # Security check: Ensure employee_id matches token (or its fallback 'sub')
    sub = user_context.get("sub", "")
    valid_ids = [str(user_context["employeeId"]).strip().lower(), sub.strip().lower(), sub.split("@")[0].strip().lower() if "@" in sub else ""]
    req_id = employee_id.strip().lower()
    
    if req_id not in valid_ids:
        import logging
        logging.getLogger("xeva").error(f"Employee ID mismatch! Request: {repr(employee_id)}, Token: {repr(user_context['employeeId'])}, Sub: {repr(sub)}")
        raise HTTPException(status_code=403, detail="Employee ID mismatch")

    if not check_input_safety(message):
        return {
            "status": "success",
            "message": "I cannot fulfill this request as it violates safety guidelines.",
            "data": None
        }

    sid = session_id or conversation_id or str(uuid.uuid4())
    
    import os
    from pathlib import Path
    # Process the file and save to temp directory
    content = await files.read()
    file_context = parse_file_for_agent(files.filename, content, files.content_type)
    
    downloads_dir = Path(__file__).resolve().parent.parent.parent / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    
    temp_dir = Path("D:/tmp/xevyte_uploads") if os.name == "nt" else Path("/tmp/xevyte_uploads")
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_file_path = str(temp_dir / f"{uuid.uuid4()}_{files.filename}")
    with open(temp_file_path, "wb") as temp_file:
        temp_file.write(content)
        
    # Also save to static downloads for frontend preview / inspection
    download_file_path = downloads_dir / files.filename
    with open(download_file_path, "wb") as dl_file:
        dl_file.write(content)
    
    # Ensure session exists in DB to prevent foreign key violation
    stmt = select(ChatSession).where(ChatSession.id == sid)
    res = await db.execute(stmt)
    if not res.scalar_one_or_none():
        db.add(ChatSession(id=sid, employee_id=user_context["employeeId"], title="New Chat"))
        await db.commit()

    # Save the user message to DB cleanly without duplicate attachment tags
    clean_user_msg = message
    if f"[Attached file: {files.filename}]" not in clean_user_msg and f"📎 {files.filename}" not in clean_user_msg:
        clean_user_msg = f"{clean_user_msg}\n\n[Attached file: {files.filename}]"

    user_msg_db = ChatMessage(
        id=str(uuid.uuid4()),
        session_id=sid,
        role="user",
        content=clean_user_msg
    )
    db.add(user_msg_db)
    await db.commit()

    # Pass everything to the agent engine
    history_obj = AsyncPostgresChatMessageHistory(session_id=sid, async_session=db)
    history_messages = await history_obj.aget_messages()
    history_dicts = [{"role": "user" if m.type == "human" else "assistant", "content": m.content} for m in history_messages if m.type in ["human", "ai"]]

    result = await run_agent(message, history_dicts, user_context, authorization, file_context, temp_file_path)

    ai_content = result.get("content", "")
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
        "data": result.get("data"),
        "pending_confirmation_token": result.get("pending_confirmation_token")
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
        
    # Security check: Ensure employee_id matches token (or its fallback 'sub')
    sub = user_context.get("sub", "")
    valid_ids = [str(user_context["employeeId"]).strip().lower(), sub.strip().lower(), sub.split("@")[0].strip().lower() if "@" in sub else ""]
    req_id = request.employee_id.strip().lower()
    
    if req_id not in valid_ids:
        import logging
        logging.getLogger("xeva").error(f"Employee ID mismatch! Request: {repr(request.employee_id)}, Token: {repr(user_context['employeeId'])}, Sub: {repr(sub)}")
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
        # Ensure session exists in DB before creating messages
        stmt = select(ChatSession).where(ChatSession.id == request.session_id)
        res = await db.execute(stmt)
        if not res.scalar_one_or_none():
            db.add(ChatSession(id=request.session_id, employee_id=user_context["employeeId"], title="New Chat"))
            await db.commit()

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

async def _execute_single_action(client: httpx.AsyncClient, action_data: dict, headers: dict, user_context: dict, settings) -> tuple[bool, Any]:
    path = action_data.get("path", "")
    url = f"{settings.JAVA_BACKEND_URL}{path}"
    method = action_data.get("method", "GET")
    
    if action_data.get("endpoint_id") in ["updateProfile", "updateEmployeeBankDetails", "updateEmployeePersonalDetails"]:
        core_fields = ["contactNo", "emergencyContactNumber", "personalMail", "address", "presentAddress", "profilePic"]
        personal_fields = ["about", "whatILoveAboutMyJob", "interestsAndHobbies"]
        bank_fields_map = {
            "bankname": "bankName",
            "accountnumber": "bankAccountNumber",
            "ifsccode": "bankIfscCode",
            "uannumber": "uanNumber",
            "pfmemberid": "pfMemberId",
            "pfaccountnumber": "pfAccountNumber",
            "esinumber": "esiNumber",
            "esiinsurancenumber": "esiInsuranceNumber",
            "esiclinicname": "esiClinicName"
        }
        
        body = action_data.get("body", {})
        
        # Flatten body in case the LLM nested fields (e.g. under 'bankDetails' or 'pfDetails')
        flat_body = {}
        for k, v in body.items():
            if isinstance(v, dict):
                for sub_k, sub_v in v.items():
                    flat_body[sub_k] = sub_v
            else:
                flat_body[k] = v
        
        # Normalize body keys to match expected camelCase
        normalized_body = {}
        for k, v in flat_body.items():
            lk = k.lower()
            if lk in bank_fields_map:
                normalized_body[bank_fields_map[lk]] = v
            else:
                matched = False
                for cf in core_fields + personal_fields + ["employeeId"]:
                    if cf.lower() == lk:
                        normalized_body[cf] = v
                        matched = True
                        break
                if not matched:
                    normalized_body[k] = v

        core_body = {k: v for k, v in normalized_body.items() if k in core_fields or k == "employeeId"}
        personal_body = {k: v for k, v in normalized_body.items() if k in personal_fields or k == "employeeId"}
        bank_body = {k: v for k, v in normalized_body.items() if k in bank_fields_map.values() or k == "employeeId"}
        
        headers_copy = dict(headers)
        headers_copy["Content-Type"] = "application/json"
        responses = []
        
        emp_id = user_context.get("employeeId")
        
        if any(k in core_fields for k in core_body.keys()):
            core_url = f"{settings.JAVA_BACKEND_URL}/api/employees/{emp_id}"
            core_resp = await client.put(core_url, headers=headers_copy, json=core_body)
            responses.append(core_resp)
        
        if any(k in personal_fields for k in personal_body.keys()):
            personal_url = f"{settings.JAVA_BACKEND_URL}/api/employees/{emp_id}/personal-details"
            personal_resp = await client.put(personal_url, headers=headers_copy, json=personal_body)
            responses.append(personal_resp)
            
        if any(k in bank_fields_map.values() for k in bank_body.keys()):
            bank_url = f"{settings.JAVA_BACKEND_URL}/api/employees/{emp_id}/bank-details"
            bank_resp = await client.put(bank_url, headers=headers_copy, json=bank_body)
            responses.append(bank_resp)
            
        is_success = all(r.is_success for r in responses) if responses else True
        resp_data = []
        for r in responses:
            try:
                resp_data.append(r.json())
            except Exception:
                resp_data.append(r.text)
        return is_success, resp_data

    if action_data.get("endpoint_id") == "createAsset" or (path == "/api/assets" and method == "POST"):
        q_params = dict(action_data.get("query_params") or {})
        if "userId" not in q_params:
            q_params["userId"] = user_context.get("employeeId", "scaloz_admin")
            
        body = action_data.get("body")
        items = body if isinstance(body, list) else (body.get("assets") if isinstance(body, dict) and isinstance(body.get("assets"), list) else [body] if isinstance(body, dict) else [])
        
        headers_copy = dict(headers)
        headers_copy["Content-Type"] = "application/json"
        
        responses = []
        import time
        import random
        
        # Fetch current categories
        current_cats = []
        try:
            r_c = await client.get(f"{settings.JAVA_BACKEND_URL}/api/assets/categories", headers=headers_copy)
            if r_c.status_code == 200:
                current_cats = r_c.json()
        except Exception:
            pass

        for it in items:
            if not isinstance(it, dict):
                continue
            clean_it = dict(it)
            cat_name = ""
            subcat_name = ""
            
            raw_cat = clean_it.pop("category", None)
            raw_subcat = clean_it.pop("subCategory", None)
            
            if clean_it.get("dynamicValues") and isinstance(clean_it["dynamicValues"], dict):
                if clean_it["dynamicValues"].get("Category"):
                    cat_name = clean_it["dynamicValues"]["Category"]
                if clean_it["dynamicValues"].get("Sub-category"):
                    subcat_name = clean_it["dynamicValues"]["Sub-category"]
                    
            cat_str = str(raw_cat or cat_name or clean_it.get("categoryId") or "").strip()
            
            matched_cat = None
            if isinstance(clean_it.get("categoryId"), int) or (isinstance(clean_it.get("categoryId"), str) and clean_it["categoryId"].isdigit()):
                c_id = int(clean_it["categoryId"])
                for c in current_cats:
                    if c.get("id") == c_id:
                        matched_cat = c
                        break
            
            if not matched_cat and cat_str:
                for c in current_cats:
                    if c.get("name", "").lower() == cat_str.lower() or c.get("name", "").lower() in cat_str.lower() or cat_str.lower() in c.get("name", "").lower():
                        matched_cat = c
                        break
                    
            if not matched_cat and cat_str and not cat_str.isdigit():
                try:
                    r_nc = await client.post(f"{settings.JAVA_BACKEND_URL}/api/assets/categories", headers=headers_copy, json={"name": cat_str.title(), "active": True})
                    if r_nc.status_code in (200, 201):
                        matched_cat = r_nc.json()
                        matched_cat["subCategories"] = []
                        current_cats.append(matched_cat)
                except Exception:
                    pass
                    
            if matched_cat:
                clean_it["categoryId"] = matched_cat["id"]
                cat_name = matched_cat.get("name", cat_str).title()
                
                sub_list = matched_cat.get("subCategories") or []
                sub_target = str(raw_subcat or subcat_name or (cat_name + "s" if not cat_name.endswith("s") else cat_name)).strip()
                matched_sub = None
                
                if isinstance(clean_it.get("subCategoryId"), int) or (isinstance(clean_it.get("subCategoryId"), str) and clean_it["subCategoryId"].isdigit()):
                    s_id = int(clean_it["subCategoryId"])
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
                    clean_it["subCategoryId"] = matched_sub["id"]
                    subcat_name = matched_sub.get("name", sub_target).title()
                elif sub_list and not (raw_subcat or subcat_name):
                    clean_it["subCategoryId"] = sub_list[0]["id"]
                    subcat_name = sub_list[0].get("name", sub_target).title()
                else:
                    try:
                        r_new_sub = await client.post(
                            f"{settings.JAVA_BACKEND_URL}/api/assets/categories",
                            headers=headers_copy,
                            json={"name": sub_target.title(), "active": True, "fieldConfigs": [], "parentCategory": {"id": matched_cat["id"]}}
                        )
                        if r_new_sub.status_code in (200, 201):
                            new_sub_obj = r_new_sub.json()
                            clean_it["subCategoryId"] = new_sub_obj.get("id")
                            subcat_name = new_sub_obj.get("name", sub_target).title()
                    except Exception:
                        pass
                
            ts = int(time.time() * 1000)
            rnd = random.randint(100, 999)
            raw_tag = clean_it.get("assetTag")
            if not raw_tag:
                clean_it["assetTag"] = f"AST-{ts}-{rnd}"
            elif not raw_tag.startswith("AST-"):
                clean_it["assetTag"] = f"AST-{raw_tag}-{rnd}"
                
            if "status" not in clean_it:
                clean_it["status"] = "IN_STOCK"
            if "conditionAtStock" not in clean_it:
                clean_it["conditionAtStock"] = "NEW"
                
            clean_it["dynamicValues"] = {
                "Category": cat_name.title() if cat_name else "Asset",
                "Sub-category": subcat_name.title() if subcat_name else "General",
                "Asset Tag": clean_it["assetTag"]
            }

            r = await client.post(url, headers=headers_copy, params=q_params, json=clean_it)
            responses.append(r)
            
        is_success = all(r.is_success for r in responses) if responses else True
        resp_data = []
        for r in responses:
            try:
                resp_data.append(r.json())
            except Exception:
                resp_data.append(r.text)
        return is_success, (resp_data[0] if len(resp_data) == 1 else resp_data)

    q_params = dict(action_data.get("query_params") or {})
    if path.startswith("/api/assets"):
        if "userId" not in q_params:
            q_params["userId"] = user_context.get("employeeId", "scaloz_admin")

    if path.startswith("/api/claims/approve/") or path.startswith("/api/claims/reject/"):
        cur_role = str(q_params.get("role", "")).lower()
        q_params["role"] = "Finance" if "finance" in cur_role else "Manager"
        if "approverId" not in q_params:
            q_params["approverId"] = user_context.get("employeeId", "")

    if path.startswith("/api/tickets/manager/reject/"):
        if isinstance(action_data.get("body"), dict) and action_data["body"].get("reason"):
            q_params["reason"] = action_data["body"]["reason"]

    req_headers = dict(headers)
    if path == "/api/tickets/team-tickets":
        req_headers["employeeId"] = user_context.get("employeeId", "scaloz_admin")

    if path.startswith("/api/v1/exit-management/") or path.startswith("/api/v1/exit-forms"):
        emp_id = user_context.get("employeeId", "")
        emp_name = user_context.get("name") or user_context.get("employeeName") or emp_id
        mgr_id = user_context.get("reportingManager") or user_context.get("managerId") or emp_id
        mgr_name = user_context.get("managerName") or emp_name
        dept = user_context.get("department") or "Admin"
        
        req_headers["employeeId"] = emp_id
        req_headers["employeeName"] = emp_name
        req_headers["managerId"] = mgr_id
        req_headers["managerName"] = mgr_name
        req_headers["department"] = dept

    request_kwargs = {
        "url": url,
        "headers": req_headers,
        "params": q_params or None,
    }
    if path.startswith("/api/travel/admin/upload-pdfs/"):
        import mimetypes
        if action_data.get("temp_file_path") and os.path.exists(action_data["temp_file_path"]):
            temp_path = action_data["temp_file_path"]
            orig_name = os.path.basename(temp_path).split("_", 1)[-1]
            mime, _ = mimetypes.guess_type(orig_name)
            with open(temp_path, "rb") as f:
                request_kwargs["files"] = {"files": (orig_name, f.read(), mime or "application/pdf")}
    elif path == "/api/employees/bulk-onboard":
        import mimetypes
        temp_path = action_data.get("temp_file_path")
        if not temp_path or not os.path.exists(temp_path):
            # Fallback to search /tmp/xevyte_uploads if path not explicitly in action_data
            upload_dir = "/tmp/xevyte_uploads"
            if os.path.exists(upload_dir):
                files_in_dir = [os.path.join(upload_dir, f) for f in os.listdir(upload_dir) if f.endswith(".csv") or f.endswith(".xlsx")]
                if files_in_dir:
                    files_in_dir.sort(key=os.path.getmtime, reverse=True)
                    temp_path = files_in_dir[0]
        if temp_path and os.path.exists(temp_path):
            orig_name = os.path.basename(temp_path).split("_", 1)[-1]
            mime, _ = mimetypes.guess_type(orig_name)
            with open(temp_path, "rb") as f:
                request_kwargs["files"] = {"file": (orig_name, f.read(), mime or "application/octet-stream")}
    elif path in ("/api/tickets/submit", "/api/tickets/change-request/submit", "/api/tickets/draft", "/api/tickets/change-request/draft"):
        form_payload = dict(action_data.get("body") or {})
        if "employeeId" not in form_payload:
            form_payload["employeeId"] = user_context.get("employeeId", "scaloz_admin")
        if "ccToManager" in form_payload:
            form_payload["ccToManager"] = str(form_payload["ccToManager"]).lower()
        request_kwargs["data"] = form_payload
        if action_data.get("temp_file_path") and os.path.exists(action_data["temp_file_path"]):
            import mimetypes
            temp_path = action_data["temp_file_path"]
            orig_name = os.path.basename(temp_path).split("_", 1)[-1]
            mime, _ = mimetypes.guess_type(orig_name)
            with open(temp_path, "rb") as f:
                request_kwargs["files"] = {"file": (orig_name, f.read(), mime or "application/octet-stream")}
    elif path == "/api/grievances/anonymous":
        parts = {k: (None, str(v)) for k, v in (action_data.get("body") or {}).items() if v is not None}
        if action_data.get("temp_file_path") and os.path.exists(action_data["temp_file_path"]):
            import mimetypes
            temp_path = action_data["temp_file_path"]
            orig_name = os.path.basename(temp_path).split("_", 1)[-1]
            mime, _ = mimetypes.guess_type(orig_name)
            with open(temp_path, "rb") as f:
                parts["attachment"] = (orig_name, f.read(), mime or "application/octet-stream")
        request_kwargs["files"] = parts
    elif path == "/api/customers" or (path.startswith("/api/customers/") and action_data.get("method") == "PUT"):
        parts = {}
        for k, v in (action_data.get("body") or {}).items():
            if k not in ("msaDoc", "file", "attachment") and v is not None:
                parts[k] = (None, str(v))
        if action_data.get("temp_file_path") and os.path.exists(action_data["temp_file_path"]):
            import mimetypes
            temp_path = action_data["temp_file_path"]
            orig_name = os.path.basename(temp_path).split("_", 1)[-1]
            mime, _ = mimetypes.guess_type(orig_name)
            with open(temp_path, "rb") as f:
                parts["msaDoc"] = (orig_name, f.read(), mime or "application/pdf")
        request_kwargs["files"] = parts
    elif path == "/api/leaves/apply":
        import json
        request_kwargs["files"] = {"dto": (None, json.dumps(action_data.get("body") or {}), "application/json")}
    elif path == "/api/claims/submit":
        import json
        import mimetypes
        request_kwargs["files"] = {"claim": (None, json.dumps(action_data.get("body") or {}), "application/json")}
        if action_data.get("temp_file_path") and os.path.exists(action_data["temp_file_path"]):
            temp_path = action_data["temp_file_path"]
            orig_name = os.path.basename(temp_path).split("_", 1)[-1]
            mime, _ = mimetypes.guess_type(orig_name)
            with open(temp_path, "rb") as f:
                request_kwargs["files"]["receiptFile"] = (orig_name, f.read(), mime or "application/octet-stream")
    elif path == "/api/claims/draft":
        import json
        import mimetypes
        request_kwargs["files"] = {"claimDraft": (None, json.dumps(action_data.get("body") or {}), "application/json")}
        if action_data.get("temp_file_path") and os.path.exists(action_data["temp_file_path"]):
            temp_path = action_data["temp_file_path"]
            orig_name = os.path.basename(temp_path).split("_", 1)[-1]
            mime, _ = mimetypes.guess_type(orig_name)
            with open(temp_path, "rb") as f:
                request_kwargs["files"]["receiptFile"] = (orig_name, f.read(), mime or "application/octet-stream")
    elif path.startswith("/api/profile/update/"):
        b = action_data.get("body") or {}
        request_kwargs["data"] = {
            "firstName": b.get("firstName", "User"),
            "lastName": b.get("lastName", "")
        }
        if action_data.get("temp_file_path") and os.path.exists(action_data["temp_file_path"]):
            with open(action_data["temp_file_path"], "rb") as f:
                request_kwargs["files"] = {"profilePic": (os.path.basename(action_data["temp_file_path"]), f.read(), "image/jpeg")}
    elif action_data.get("body"):
        req_headers["Content-Type"] = "application/json"
        request_kwargs["json"] = action_data["body"]
        
    if "files" in request_kwargs and "Content-Type" in req_headers:
        # httpx needs to automatically set the multipart/form-data boundary
        del req_headers["Content-Type"]
        
    # Also clean up lowercase variants just in case
    if "files" in request_kwargs and "content-type" in req_headers:
        del req_headers["content-type"]
        
    response = await client.request(method, **request_kwargs)
    try:
        resp_data = response.json()
    except Exception:
        resp_data = response.text
    
    is_success = response.is_success
    # Check for soft error messages inside 200 responses from Spring Boot
    if is_success:
        if isinstance(resp_data, dict):
            status_in_body = resp_data.get("status")
            if status_in_body in (400, 401, 403, 404, 500, "error", "failed") or resp_data.get("error"):
                is_success = False
            elif any(err_kw in str(resp_data.get("message", "")).lower() for err_kw in ("not authorized", "cannot", "failed", "error", "invalid")):
                is_success = False
        elif isinstance(resp_data, str):
            lower_txt = resp_data.lower()
            if any(err_kw in lower_txt for err_kw in ("not authorized", "cannot", "only the", "failed to", "error:")):
                is_success = False
    
    # Cleanup temp file
    if action_data.get("temp_file_path") and os.path.exists(action_data["temp_file_path"]):
        try:
            os.remove(action_data["temp_file_path"])
        except Exception as e:
            print(f"Failed to clean up temp file: {e}")
            
    return is_success, resp_data

def _format_single_action_label(act: dict) -> str:
    ep = act.get("endpoint_id", "")
    body = act.get("body") or {}
    path_params = act.get("path_params") or {}
    
    if ep == "rejectLeave":
        req_id = body.get("leaveRequestId") or path_params.get("id") or ""
        return f"Reject Leave Request #{req_id}" if req_id else "Reject Leave Request"
    elif ep == "approveLeave":
        req_id = body.get("leaveRequestId") or path_params.get("id") or ""
        return f"Approve Leave Request #{req_id}" if req_id else "Approve Leave Request"
    elif ep == "rejectClaim":
        req_id = path_params.get("id") or body.get("id") or ""
        return f"Reject Expense Claim #{req_id}" if req_id else "Reject Expense Claim"
    elif ep == "approveClaim":
        req_id = path_params.get("id") or body.get("id") or ""
        return f"Approve Expense Claim #{req_id}" if req_id else "Approve Expense Claim"
    elif ep == "rejectCompensation":
        req_id = body.get("id") or path_params.get("id") or ""
        return f"Reject Compensation Revision #{req_id}" if req_id else "Reject Compensation Revision"
    elif ep == "approveCompensation":
        req_id = body.get("id") or path_params.get("id") or ""
        return f"Approve Compensation Revision #{req_id}" if req_id else "Approve Compensation Revision"
    elif ep == "applyLeave":
        return f"Apply Leave ({body.get('type', 'Leave')})"
    elif ep == "submitClaim":
        return f"Submit Claim ({body.get('category', 'Expense')})"
    elif ep == "submitTicket":
        return f"Submit Ticket ({body.get('issueSummary', 'Support')})"
    return ep or act.get("path", "Action")

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
    token_str = authorization[7:] if authorization.startswith("Bearer ") else authorization
    headers = {
        "Authorization": f"Bearer {token_str}"
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if action_data.get("is_batch"):
                actions = action_data.get("actions", [])
                action_results = []
                for act in actions:
                    succ, res = await _execute_single_action(client, act, headers, user_context, settings)
                    action_results.append((act, succ, res))

                success_lines = []
                failed_lines = []
                
                for act, succ, res in action_results:
                    label = _format_single_action_label(act)
                    if succ:
                        success_lines.append(f"- ✅ **{label}**: Successfully executed.")
                    else:
                        err_text = "Unable to process request"
                        if isinstance(res, dict):
                            err_text = res.get("message") or res.get("error") or res.get("detail") or str(res)
                        elif isinstance(res, str):
                            err_text = res
                        failed_lines.append(f"- ❌ **{label}**: Failed — {err_text}")

                if success_lines and not failed_lines:
                    success_msg = "✅ **All actions completed successfully:**\n\n" + "\n".join(success_lines)
                elif success_lines and failed_lines:
                    success_msg = "⚠️ **Action Results (Partial Completion):**\n\n" + "\n".join(success_lines) + "\n" + "\n".join(failed_lines)
                else:
                    success_msg = "❌ **Actions failed:**\n\n" + "\n".join(failed_lines)
                    
                resp_data = [res for _, _, res in action_results]
            else:
                is_success, resp_data = await _execute_single_action(client, action_data, headers, user_context, settings)
                label = _format_single_action_label(action_data)
                
                if is_success:
                    if isinstance(resp_data, dict) and "totalRecords" in resp_data and "successCount" in resp_data:
                        total = resp_data.get("totalRecords", 0)
                        succ_cnt = resp_data.get("successCount", 0)
                        failures = resp_data.get("failureDetails", [])
                        if succ_cnt == total and total > 0:
                            success_msg = f"Bulk onboarding completed successfully! All {succ_cnt} employees were added."
                        elif succ_cnt > 0:
                            err_reasons = [f"Row {f.get('rowNumber')}: {f.get('reason')}" for f in failures]
                            success_msg = f"Bulk onboarding partially completed: {succ_cnt}/{total} succeeded, {len(failures)} failed.\nFailures:\n" + "\n".join(err_reasons)
                        else:
                            err_reasons = [f"Row {f.get('rowNumber')}: {f.get('reason')}" for f in failures]
                            success_msg = f"Bulk onboarding failed: 0/{total} employees onboarded.\nReason(s):\n" + ("\n".join(err_reasons) if err_reasons else "Unknown validation error")
                    elif action_data.get("endpoint_id") == "generatePayslips" or action_data.get("path") == "/api/payroll/generate-payslips":
                        b = action_data.get("body") or {}
                        target_month = b.get("month", "the selected month")
                        target_year = b.get("year", "the selected year")
                        count = 0
                        if isinstance(resp_data, list):
                            count = len(resp_data)
                        elif isinstance(resp_data, dict):
                            if "count" in resp_data:
                                try:
                                    count = int(resp_data["count"])
                                except Exception:
                                    count = 0
                            elif "payslips" in resp_data and isinstance(resp_data["payslips"], list):
                                count = len(resp_data["payslips"])
                            elif "id" in resp_data or "employeeId" in resp_data:
                                count = 1
                        
                        if count == 0:
                            success_msg = f"⚠️ 0 payslips were generated for {target_month} {target_year}.\n\nReason: No salary configuration Excel exists for {target_month} {target_year} in the HRMS (or all employees for this period already have payslips generated). Please upload the salary configuration for {target_month} {target_year} before generating."
                        else:
                            success_msg = f"✅ Successfully generated {count} payslip(s) for {target_month} {target_year}!"
                    else:
                        success_msg = f"✅ **{label}**: Action completed successfully!"
                else:
                    if isinstance(resp_data, dict):
                        err_msg = resp_data.get("message") or resp_data.get("error") or resp_data.get("detail") or str(resp_data)
                    else:
                        err_msg = str(resp_data)
                    success_msg = f"❌ **{label}** failed: {err_msg}"
                
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
