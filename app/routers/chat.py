from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from app.agent import nodes
from app.agent.graph import get_agent_graph
from app.agent.state import AgentState
from app.agent.memory import summarize_history
from app.auth import sessions
from app.catalog.loader import get_catalog
from app.database import get_db
from app.db_models import AgentSession, AuditLog, Conversation, Message
from app.guardrails.pii import redact
from app.guardrails.risk import classify
from app.routers.auth_routes import get_current_session
from app.schemas import ChatRequest, ChatResponse, ConfirmRequest, EndpointCallSummary
from app.config import get_settings

router = APIRouter(prefix="/api/agent", tags=["chat"])

MAX_HISTORY_MESSAGES = 40

_AFFIRM = {"yes", "y", "yeah", "yep", "ok", "okay", "sure", "go ahead", "proceed", "confirm", "do it", "approve"}
_DECLINE = {"no", "n", "nope", "cancel", "don't", "do not", "stop", "reject", "decline"}


def _normalize_confirm_reply(text: str) -> str | None:
    """Return 'approve' | 'decline' | None for short free-text confirmation replies."""
    t = (text or "").strip().lower().rstrip(".!")
    if t in _AFFIRM:
        return "approve"
    if t in _DECLINE:
        return "decline"
    # mild phrases
    if t.startswith("yes ") or t.startswith("ok ") or "go ahead" in t:
        return "approve"
    if t.startswith("no ") or "don't" in t or "do not" in t:
        return "decline"
    return None


def _latest_pending_assistant(db: DBSession, conversation_id: str) -> Message | None:
    return (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id, Message.role == "assistant")
        .order_by(Message.created_at.desc())
        .first()
    )


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
            # Respect the frontend's requested UUID so /confirm doesn't 404 later
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


def _load_history(db: DBSession, conversation_id: str) -> list[dict]:
    rows = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .limit(MAX_HISTORY_MESSAGES)
        .all()
    )
    return [{"role": r.role, "content": r.content} for r in rows]


def _write_audit_log(db: DBSession, session: AgentSession, conversation_id: str, state: dict, user_confirmed: bool = False) -> None:
    planned = state.get("planned_call")
    execution = state.get("execution") or {}
    if not planned:
        return
    endpoint = get_catalog().get(planned["endpoint_id"])
    if not endpoint:
        return
    db.add(
        AuditLog(
            session_id=session.id,
            conversation_id=conversation_id,
            employee_id=session.employee_id,
            endpoint_id=endpoint.id,
            http_method=endpoint.http_method,
            path=endpoint.path,
            risk_tier=state.get("risk_tier") or classify(endpoint).value,
            user_confirmed=user_confirmed,
            request_summary=redact(
                {"path_args": planned.get("path_args"), "query_args": planned.get("query_args"), "body": planned.get("body")}
            ),
            response_status=execution.get("status_code"),
            response_summary=redact(execution.get("body")),
            success=bool(execution.get("ok")),
            error_message=execution.get("error"),
            latency_ms=execution.get("latency_ms"),
        )
    )
    db.commit()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    session: AgentSession = Depends(get_current_session),
    db: DBSession = Depends(get_db),
) -> ChatResponse:
    bearer_token = sessions.get_bearer_token(session)
    if not bearer_token:
        raise HTTPException(status_code=401, detail="Could not decrypt session token — please log in again.")

    settings = get_settings()
    if not (settings.OPENAI_API_KEY or "").strip():
        raise HTTPException(
            status_code=503,
            detail=(
                "Agent LLM is not configured: OPENAI_API_KEY is missing. "
                "Copy .env.example to .env, set your API key, restart the agent, then try again."
            ),
        )

    conversation = _get_or_create_conversation(db, session, body.conversation_id)
    history = _load_history(db, conversation.id)

    # Free-text yes/no after a needs_confirmation turn — avoid re-planning loops
    pending_msg = _latest_pending_assistant(db, conversation.id)
    decision = _normalize_confirm_reply(body.message)
    if (
        decision
        and pending_msg
        and pending_msg.trace
        and pending_msg.trace.get("pending_confirmation_token")
        and pending_msg.trace.get("planned_call")
    ):
        return await confirm(
            ConfirmRequest(
                conversation_id=conversation.id,
                pending_confirmation_token=pending_msg.trace["pending_confirmation_token"],
                approve=(decision == "approve"),
            ),
            session=session,
            db=db,
        )
    
    # --- Summary Memory Middleware ---
    # If the conversation is getting long, summarize the older messages to save context window,
    # without deleting them from the DB (so the frontend UI remains unaffected).
    if len(history) > 10:
        old_history = history[:-5]
        recent_history = history[-5:]
        try:
            summary_text = await summarize_history(old_history)
            # Cap summary size to protect planner context
            if len(summary_text) > 2500:
                summary_text = summary_text[:2500] + "...[truncated]"
            history = [{"role": "system", "content": f"Summary of earlier conversation:\n{summary_text}"}] + recent_history
        except Exception:
            history = recent_history
    # ---------------------------------

    db.add(Message(conversation_id=conversation.id, role="user", content=body.message))
    db.commit()

    # Append the current user message to the history passed to the agent
    history.append({"role": "user", "content": body.message})

    initial_state: AgentState = {
        "user_message": body.message,
        "conversation_history": history,
        "bearer_token": bearer_token,
        "employee_id": session.employee_id,
        "role": session.role,
    }

    try:
        final_state = await get_agent_graph().ainvoke(initial_state)
    except Exception as e:
        err_reply = f"I hit an internal error while handling that ({e}). Please try again."
        db.add(Message(conversation_id=conversation.id, role="assistant", content=err_reply, trace={"error": str(e)}))
        db.commit()
        return ChatResponse(conversation_id=conversation.id, reply=err_reply, status="error")

    pending_token = None
    trace = {
        "retrieved": final_state.get("retrieved"),
        "planned_call": final_state.get("planned_call"),
        "risk_tier": final_state.get("risk_tier"),
        "execution": redact(final_state.get("execution")) if final_state.get("execution") else None,
    }
    if final_state.get("status") == "needs_confirmation":
        pending_token = secrets.token_urlsafe(16)
        trace["pending_confirmation_token"] = pending_token

    reply = final_state.get("reply") or "I wasn't able to produce a reply for that."
    db.add(Message(conversation_id=conversation.id, role="assistant", content=reply, trace=trace))
    db.commit()

    if final_state.get("execution") is not None:
        _write_audit_log(db, session, conversation.id, final_state)

    candidate_call = None
    planned = final_state.get("planned_call")
    if planned and planned.get("endpoint_id"):
        ep = get_catalog().get(planned["endpoint_id"])
        if ep:
            candidate_call = EndpointCallSummary(
                endpoint_id=ep.id, http_method=ep.http_method, path=ep.path, module=ep.module,
                risk_tier=final_state.get("risk_tier") or "LOW",
            )

    execution = final_state.get("execution")
    return ChatResponse(
        conversation_id=conversation.id,
        reply=final_state.get("reply", ""),
        status=final_state.get("status", "completed"),
        candidate_call=candidate_call,
        pending_confirmation_token=pending_token,
        missing_info=(planned or {}).get("missing_info", []),
        raw_result=execution.get("body") if execution else None,
    )


@router.post("/confirm", response_model=ChatResponse)
async def confirm(
    body: ConfirmRequest,
    session: AgentSession = Depends(get_current_session),
    db: DBSession = Depends(get_db),
) -> ChatResponse:
    conversation = db.get(Conversation, body.conversation_id)
    if not conversation or conversation.session_id != session.id:
        raise HTTPException(status_code=404, detail="Conversation not found")

    pending_msg = (
        db.query(Message)
        .filter(Message.conversation_id == conversation.id, Message.role == "assistant")
        .order_by(Message.created_at.desc())
        .first()
    )
    if (
        not pending_msg
        or not pending_msg.trace
        or pending_msg.trace.get("pending_confirmation_token") != body.pending_confirmation_token
    ):
        raise HTTPException(
            status_code=400,
            detail="No matching pending confirmation found — it may have expired or already been actioned.",
        )

    if not body.approve:
        reply = "Okay, I won't go ahead with that."
        db.add(Message(conversation_id=conversation.id, role="assistant", content=reply))
        db.commit()
        return ChatResponse(conversation_id=conversation.id, reply=reply, status="completed")

    bearer_token = sessions.get_bearer_token(session)
    if not bearer_token:
        raise HTTPException(status_code=401, detail="Could not decrypt session token — please log in again.")

    history = _load_history(db, conversation.id)
    if len(history) > 10:
        old_history = history[:-5]
        recent_history = history[-5:]
        summary_text = await summarize_history(old_history)
        history = [{"role": "system", "content": f"Summary of earlier conversation:\n{summary_text}"}] + recent_history
    
    history.append({"role": "user", "content": "(confirmed pending action)"})

    state: AgentState = {
        "user_message": "(confirmed pending action)",
        "conversation_history": history,
        "planned_call": pending_msg.trace.get("planned_call"),
        "risk_tier": pending_msg.trace.get("risk_tier"),
        "bearer_token": bearer_token,
        "employee_id": session.employee_id,
        "role": session.role,
    }
    state.update(await nodes.execute_node(state))
    state.update(await nodes.respond_node(state))

    trace = {
        "planned_call": state.get("planned_call"),
        "risk_tier": state.get("risk_tier"),
        "execution": redact(state.get("execution")),
    }
    db.add(Message(conversation_id=conversation.id, role="assistant", content=state.get("reply", ""), trace=trace))
    db.commit()

    _write_audit_log(db, session, conversation.id, state, user_confirmed=True)

    execution = state.get("execution")
    return ChatResponse(
        conversation_id=conversation.id,
        reply=state.get("reply", ""),
        status=state.get("status", "completed"),
        raw_result=execution.get("body") if execution else None,
    )
