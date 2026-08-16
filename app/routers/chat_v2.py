from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.auth import sessions
from app.database import get_db
from app.db_models import AgentSession, Conversation, Message
from app.routers.auth_routes import get_current_session
from app.workflow.pipeline import handle_message, resume_after_approval

router = APIRouter(prefix="/api/agent/v2", tags=["chat-v2-enterprise"])


class ChatRequestV2(BaseModel):
    message: str
    conversation_id: str | None = None


class ConfirmRequestV2(BaseModel):
    conversation_id: str
    run_id: str
    approval_id: str
    approve: bool


def _get_or_create_conversation(db: DBSession, session: AgentSession, conversation_id: str | None) -> Conversation:
    if conversation_id:
        conv = db.get(Conversation, conversation_id)
        if conv:
            if conv.session and conv.session.employee_id == session.employee_id:
                if conv.session_id != session.id:
                    conv.session_id = session.id
                    db.commit()
                    db.refresh(conv)
                return conv
            else:
                raise HTTPException(status_code=403, detail="Access denied to this conversation")
        else:
            conv = Conversation(id=conversation_id, session_id=session.id)
            db.add(conv)
            db.commit()
            db.refresh(conv)
            return conv
    conv = Conversation(session_id=session.id)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


async def _load_history(db: DBSession, conversation_id: str) -> list[dict]:
    rows = (db.query(Message).filter(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc()).limit(40).all())
    history = [{"role": r.role, "content": r.content} for r in rows]
    if len(history) > 10:
        old_history = history[:-5]
        recent_history = history[-5:]
        try:
            from app.agent.memory import summarize_history
            summary_text = await summarize_history(old_history)
            if len(summary_text) > 2500:
                summary_text = summary_text[:2500] + "...[truncated]"
            history = [{"role": "system", "content": f"Summary of earlier conversation:\n{summary_text}"}] + recent_history
        except Exception:
            history = recent_history
    return history


@router.post("/chat")
async def chat_v2(body: ChatRequestV2, session: AgentSession = Depends(get_current_session), db: DBSession = Depends(get_db)):
    bearer_token = sessions.get_bearer_token(session)
    conversation = _get_or_create_conversation(db, session, body.conversation_id)
    history = await _load_history(db, conversation.id)
    db.add(Message(conversation_id=conversation.id, role="user", content=body.message))
    db.commit()

    result = await handle_message(
        db, conversation_id=conversation.id, session_id=session.id, employee_id=session.employee_id,
        role=session.role, tenant_id=session.tenant_id, bearer_token=bearer_token,
        user_message=body.message, conversation_history=history,
    )

    trace = {"run_id": result.run_id, "tool_id": result.tool_id, "risk_tier": result.risk_tier,
              "pending_approval_id": result.pending_approval_id}
    db.add(Message(conversation_id=conversation.id, role="assistant", content=result.reply, trace=trace))
    db.commit()

    return {
        "conversation_id": conversation.id, "run_id": result.run_id, "status": result.status,
        "reply": result.reply, "tool_id": result.tool_id, "risk_tier": result.risk_tier,
        "pending_approval_id": result.pending_approval_id, "result": result.normalized_result,
    }


@router.post("/confirm")
async def confirm_v2(body: ConfirmRequestV2, session: AgentSession = Depends(get_current_session), db: DBSession = Depends(get_db)):
    bearer_token = sessions.get_bearer_token(session)
    conversation = db.get(Conversation, body.conversation_id)
    if not conversation or conversation.session_id != session.id:
        raise HTTPException(404, "Conversation not found")

    if body.approve:
        from app.planes.governance import approval_service
        approval_service.decide(db, body.approval_id, approved=True, approver_employee_id=session.employee_id)
    else:
        from app.planes.governance import approval_service
        approval_service.decide(db, body.approval_id, approved=False, approver_employee_id=session.employee_id)

    result = await resume_after_approval(
        db, run_id=body.run_id, approval_id=body.approval_id, approved=body.approve,
        bearer_token=bearer_token, employee_id=session.employee_id, role=session.role,
        tenant_id=session.tenant_id, user_message="(approval decision)",
    )
    db.add(Message(conversation_id=conversation.id, role="assistant", content=result.reply,
                    trace={"run_id": result.run_id, "tool_id": result.tool_id}))
    db.commit()
    return {"conversation_id": conversation.id, "status": result.status, "reply": result.reply,
            "result": result.normalized_result}
