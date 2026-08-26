import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from pydantic import BaseModel

from app.db.database import get_db
from app.db.models import ChatSession, ChatMessage
from app.auth.jwt_handler import validate_and_extract_token

router = APIRouter()

class SessionCreate(BaseModel):
    id: str = None
    title: str = "New Chat"

class SessionRename(BaseModel):
    title: str

class SessionResponse(BaseModel):
    id: str
    title: str
    is_pinned: bool
    created_at: str

@router.get("/sessions/{employee_id}")
async def list_sessions(
    employee_id: str,
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """List all sessions for a user."""
    # Basic auth validation
    if not authorization:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    user_context = validate_and_extract_token(authorization)
    if not user_context:
        raise HTTPException(status_code=401, detail="Invalid token")
        
    stmt = select(ChatSession).where(ChatSession.employee_id == user_context["employeeId"]).order_by(ChatSession.created_at.desc())
    result = await db.execute(stmt)
    sessions = result.scalars().all()
    
    return [
        {
            "id": s.id,
            "title": s.title,
            "is_pinned": s.is_pinned,
            "created_at": s.created_at.isoformat()
        } for s in sessions
    ]

@router.post("/sessions")
async def create_session(
    data: SessionCreate,
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """Create a new session."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    user_context = validate_and_extract_token(authorization)
    if not user_context:
        raise HTTPException(status_code=401, detail="Invalid token")
        
    new_id = data.id if data.id else str(uuid.uuid4())
    stmt = select(ChatSession).where(ChatSession.id == new_id)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        return {"id": existing.id, "title": existing.title, "is_pinned": existing.is_pinned}
        
    session = ChatSession(
        id=new_id,
        employee_id=user_context["employeeId"],
        title=data.title
    )
    db.add(session)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        stmt = select(ChatSession).where(ChatSession.id == new_id)
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            return {"id": existing.id, "title": existing.title, "is_pinned": existing.is_pinned}
        raise
    
    return {"id": new_id, "title": data.title, "is_pinned": False}

@router.put("/sessions/{session_id}/pin")
async def toggle_pin(
    session_id: str,
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(ChatSession).where(ChatSession.id == session_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    session.is_pinned = not session.is_pinned
    await db.commit()
    return {"id": session.id, "is_pinned": session.is_pinned}

@router.put("/sessions/{session_id}/rename")
async def rename_session(
    session_id: str,
    data: SessionRename,
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(ChatSession).where(ChatSession.id == session_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    session.title = data.title
    await db.commit()
    return {"id": session.id, "title": session.title}

@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    stmt = delete(ChatSession).where(ChatSession.id == session_id)
    await db.execute(stmt)
    await db.commit()
    return {"status": "success"}

@router.get("/sessions/{session_id}/messages")
async def get_messages(
    session_id: str,
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at)
    result = await db.execute(stmt)
    messages = result.scalars().all()
    
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat(),
            "pending_confirmation_token": m.pending_confirmation_token,
            "pending_action": m.pending_action
        } for m in messages if m.role in ("user", "assistant")
    ]

@router.get("/notifications/{employee_id}")
async def get_notifications(
    employee_id: str,
    authorization: str = Header(None)
):
    """Proxy notifications from the Java HRMS backend with authorization."""
    from app.config import get_settings
    import httpx
    import logging
    log = logging.getLogger("xeva.notifications")
    
    settings = get_settings()
    headers = {"Authorization": authorization} if authorization else {}
    target_url = f"{settings.HRMS_API_BASE_URL}/api/notifications/{employee_id}"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(target_url, headers=headers)
            if resp.is_success:
                return resp.json()
            return []
    except Exception as e:
        log.warning(f"Failed to proxy notifications for {employee_id}: {e}")
        return []

@router.get("/task-counts/{employee_id}")
async def get_task_counts(
    employee_id: str,
    authorization: str = Header(None)
):
    """Proxy task counts / pending approvals from Java HRMS backend."""
    from app.config import get_settings
    import httpx
    import logging
    log = logging.getLogger("xeva.task_counts")
    
    settings = get_settings()
    headers = {"Authorization": authorization} if authorization else {}
    target_url = f"{settings.HRMS_API_BASE_URL}/api/task-counts/{employee_id}"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(target_url, headers=headers)
            if resp.is_success:
                return resp.json()
            return {}
    except Exception as e:
        log.warning(f"Failed to proxy task counts for {employee_id}: {e}")
        return {}

@router.get("/policies/pending")
async def get_pending_policies(
    authorization: str = Header(None)
):
    """Proxy pending policy acknowledgments from Java HRMS backend."""
    from app.config import get_settings
    import httpx
    import logging
    log = logging.getLogger("xeva.policies")
    
    settings = get_settings()
    headers = {"Authorization": authorization} if authorization else {}
    target_url = f"{settings.HRMS_API_BASE_URL}/api/policies/pending"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(target_url, headers=headers)
            if resp.is_success:
                return resp.json()
            return []
    except Exception as e:
        log.warning(f"Failed to proxy pending policies: {e}")
        return []
