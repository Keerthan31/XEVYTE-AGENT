"""
Xevyte HRMS Agent — FastAPI entrypoint
"""

import os
import re
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import logging
import json
import db

from agent import run_agent, stream_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Xevyte HRMS AI Agent",
    description="Conversational AI agent for Xevyte Connect HRMS",
    version="2.0.0",
)

# ─── CORS ─────────────────────────────────────────────────────────────────────
ALLOWED_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:3008,http://localhost:5173"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Helpers ──────────────────────────────────────────────────────────────────
_TOOL_MARKER_RE = re.compile(r"__TOOL_START:[\s\S]*?__|__TOOL_END__")


def _strip_tool_markers(text: str) -> str:
    """Remove internal tool execution markers before saving to DB."""
    return _TOOL_MARKER_RE.sub("", text).strip() if text else text


# ─── Models ───────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
    token: str
    employee_id: str
    session_id: str = ""


class ChatResponse(BaseModel):
    reply: str
    history: list[ChatMessage]


class SessionCreateRequest(BaseModel):
    id: str
    employee_id: str
    title: str = "New Chat"
    is_pinned: bool = False


class SessionPinRequest(BaseModel):
    is_pinned: bool


class SessionRenameRequest(BaseModel):
    title: str


class AddMessageRequest(BaseModel):
    role: str
    content: str


class DebugRequest(BaseModel):
    tool: str
    token: str
    employee_id: str
    params: dict = {}


@app.on_event("startup")
def startup_db():
    """Initialize DB tables gracefully on server startup."""
    try:
        db.init_db()
    except Exception as e:
        logger.error(f"Startup DB init error: {e}")


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    db_ok = True
    try:
        conn = db.get_connection()
        db.release_connection(conn)
    except Exception:
        db_ok = False
    return {"status": "ok", "version": "2.1.0", "database": "connected" if db_ok else "disconnected"}


# ─── Database Chat Session Routes ──────────────────────────────────────────────

@app.get("/api/chats/sessions/{employee_id}")
def get_user_sessions(employee_id: str):
    """Retrieve all sessions for an employee from PostgreSQL."""
    sessions = db.get_employee_sessions(employee_id)
    return sessions


@app.post("/api/chats/sessions")
def create_or_update_session(req: SessionCreateRequest):
    """Create or update a chat session in PostgreSQL."""
    db.save_session(req.id, req.employee_id, req.title, req.is_pinned)
    return {"status": "success", "session_id": req.id}


@app.post("/api/chats/sessions/{session_id}/messages")
def save_message_to_db(session_id: str, req: AddMessageRequest):
    """Add a message to a chat session in PostgreSQL."""
    db.add_message(session_id, req.role, req.content)
    return {"status": "success"}


@app.put("/api/chats/sessions/{session_id}/pin")
def pin_session(session_id: str, req: SessionPinRequest):
    """Pin/unpin a session in PostgreSQL."""
    db.update_session_pin(session_id, req.is_pinned)
    return {"status": "success"}


@app.put("/api/chats/sessions/{session_id}/rename")
def rename_session(session_id: str, req: SessionRenameRequest):
    """Rename a session in PostgreSQL."""
    db.update_session_title(session_id, req.title)
    return {"status": "success"}


@app.delete("/api/chats/sessions/{session_id}")
def delete_session_endpoint(session_id: str):
    """Delete a session from PostgreSQL."""
    db.delete_session(session_id)
    return {"status": "success"}


# ─── Agent Routes ─────────────────────────────────────────────────────────────

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not req.token:
        raise HTTPException(status_code=401, detail="JWT token required.")
    if not req.employee_id:
        raise HTTPException(status_code=400, detail="employee_id required.")
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    history_dicts = [{"role": m.role, "content": m.content} for m in req.history]

    try:
        reply, updated = run_agent(
            user_message=req.message,
            history=history_dicts,
            token=req.token,
            employee_id=req.employee_id,
        )
        
        # Save to DB if session_id provided
        if req.session_id:
            db.save_session(req.session_id, req.employee_id, req.message[:28], False)
            db.add_message(req.session_id, "user", req.message)
            db.add_message(req.session_id, "assistant", reply)
            
    except Exception as e:
        logger.error(f"Agent error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")

    return ChatResponse(
        reply=reply,
        history=[ChatMessage(role=m["role"], content=m["content"]) for m in updated],
    )


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    if not req.token:
        raise HTTPException(status_code=401, detail="JWT token required.")
    if not req.employee_id:
        raise HTTPException(status_code=400, detail="employee_id required.")
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    history_dicts = [{"role": m.role, "content": m.content} for m in req.history]

    # Save user message to DB immediately
    if req.session_id:
        db.save_session(req.session_id, req.employee_id, req.message[:28], False)
        db.add_message(req.session_id, "user", req.message)

    async def event_generator():
        full_reply = ""
        try:
            async for chunk in stream_agent(
                user_message=req.message,
                history=history_dicts,
                token=req.token,
                employee_id=req.employee_id,
            ):
                full_reply += chunk
                yield f"data: {json.dumps(chunk)}\n\n"
            
            # Save final assistant reply to DB when streaming finishes
            if req.session_id and full_reply:
                clean_reply = _strip_tool_markers(full_reply)
                db.add_message(req.session_id, "assistant", clean_reply)
        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/debug/tool")
async def debug_tool(req: DebugRequest):
    from tools import ALL_TOOLS, set_session
    set_session(req.token, req.employee_id)

    tool_map = {t.name: t for t in ALL_TOOLS}
    if req.tool not in tool_map:
        raise HTTPException(status_code=404, detail=f"Tool '{req.tool}' not found. Available: {list(tool_map.keys())}")

    try:
        result = tool_map[req.tool].invoke(req.params)
        return {"tool": req.tool, "result": result}
    except Exception as e:
        logger.error(f"Tool execution error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Tool error: {str(e)}")
