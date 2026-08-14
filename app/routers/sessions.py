from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.routers.auth_routes import get_current_session
from app.database import get_db
from app.db_models import AgentSession, Conversation

router = APIRouter(prefix="/api/agent/sessions", tags=["sessions"])

class CreateSessionRequest(BaseModel):
    id: str
    employee_id: str
    title: str = "New Chat"
    is_pinned: bool = False

class PinRequest(BaseModel):
    is_pinned: bool

class RenameRequest(BaseModel):
    title: str

@router.get("/{employee_id}")
async def get_sessions(
    employee_id: str,
    session: AgentSession = Depends(get_current_session),
    db: DBSession = Depends(get_db)
) -> Any:
    # Fetch all AgentSessions for this employee so we can load all their history
    # even across different login sessions or orphaned sessions from the CORS bug.
    employee_sessions = db.query(AgentSession.id).filter(
        AgentSession.employee_id == employee_id
    ).subquery()

    conversations = (
        db.query(Conversation)
        .filter(Conversation.session_id.in_(employee_sessions))
        .order_by(Conversation.created_at.desc())
        .all()
    )
    
    # Map to frontend expected format
    return [
        {
            "id": c.id,
            "title": c.title,
            "is_pinned": c.is_pinned,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            "messages": [{"role": m.role, "content": m.content, "ts": m.created_at.timestamp() * 1000 if m.created_at else 0} for m in sorted(c.messages, key=lambda x: x.created_at)] if c.messages else [],
            "history": [{"role": m.role, "content": m.content} for m in sorted(c.messages, key=lambda x: x.created_at)] if c.messages else []
        }
        for c in conversations
    ]

@router.post("")
async def create_session(
    req: CreateSessionRequest,
    session: AgentSession = Depends(get_current_session),
    db: DBSession = Depends(get_db)
) -> Any:
    # Check if exists
    existing = db.get(Conversation, req.id)
    if existing:
        return {"status": "ok", "id": existing.id}

    conv = Conversation(
        id=req.id,
        session_id=session.id,
        title=req.title,
        is_pinned=req.is_pinned
    )
    db.add(conv)
    db.commit()
    return {"status": "ok", "id": conv.id}

@router.put("/{session_id}/pin")
async def pin_session(
    session_id: str,
    req: PinRequest,
    session: AgentSession = Depends(get_current_session),
    db: DBSession = Depends(get_db)
) -> Any:
    conv = db.get(Conversation, session_id)
    if not conv or conv.session_id != session.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    conv.is_pinned = req.is_pinned
    db.commit()
    return {"status": "ok"}

@router.put("/{session_id}/rename")
async def rename_session(
    session_id: str,
    req: RenameRequest,
    session: AgentSession = Depends(get_current_session),
    db: DBSession = Depends(get_db)
) -> Any:
    conv = db.get(Conversation, session_id)
    if not conv or conv.session_id != session.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    conv.title = req.title
    db.commit()
    return {"status": "ok"}

@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    session: AgentSession = Depends(get_current_session),
    db: DBSession = Depends(get_db)
) -> Any:
    conv = db.get(Conversation, session_id)
    if not conv or conv.session_id != session.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    db.delete(conv)
    db.commit()
    return {"status": "ok"}
