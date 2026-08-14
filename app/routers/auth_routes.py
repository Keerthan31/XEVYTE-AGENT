"""
Auth endpoints. Three ways in, because the SSO redirect-back target isn't
fully verifiable from this repo alone (see app/auth/sso.py docstring):

  1. GET  /login     -> start the real Scaloz IAM SSO flow (preferred)
  2. GET  /callback   -> IAM bounces back here with ?scaloz_token=...
  3. POST /token      -> manual fallback: paste a token you already have
                         (e.g. copied from the HRMS web app's sessionStorage
                         after a normal login) if IAM isn't yet configured
                         to redirect back to this agent.

All three end the same way: an encrypted session row in Postgres and an
HttpOnly session cookie. The agent never sees, needs, or stores an HRMS
password — only a token Scaloz IAM already issued.
"""
from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.auth import sessions, sso
from app.config import get_settings
from app.database import get_db
from app.db_models import AgentSession
from app.schemas import LoginStartResponse, SessionInfo

router = APIRouter(prefix="/api/agent/auth", tags=["auth"])


class ManualTokenRequest(BaseModel):
    token: str


def get_current_session(
    request: Request,
    db: DBSession = Depends(get_db),
) -> AgentSession:
    settings = get_settings()
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not session_id:
        raise HTTPException(status_code=401, detail="Not logged in. Call /api/agent/auth/login first.")
    session = sessions.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired or invalid. Please log in again.")
    return session


def _set_session_cookie(response: Response, session_id: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=settings.SESSION_TTL_HOURS * 3600,
    )


@router.get("/login", response_model=LoginStartResponse)
async def login(tenant: str | None = None):
    return LoginStartResponse(sso_redirect_url=sso.build_iam_login_url(tenant))


@router.get("/callback", response_class=HTMLResponse)
async def callback(scaloz_token: str | None = None, db: DBSession = Depends(get_db)):
    if not scaloz_token:
        raise HTTPException(status_code=400, detail="Missing scaloz_token in callback query string")
    session = sessions.create_session(db, scaloz_token)
    response = HTMLResponse(
        f"<html><body style='font-family:sans-serif;text-align:center;margin-top:4rem'>"
        f"<h2>Signed in{f' as {session.employee_name}' if session.employee_name else ''} ✅</h2>"
        f"<p>You can close this tab and return to your chat client.</p></body></html>"
    )
    _set_session_cookie(response, session.id)
    return response


@router.post("/token", response_model=SessionInfo)
async def manual_token(body: ManualTokenRequest, response: Response, db: DBSession = Depends(get_db)):
    session = sessions.create_session(db, body.token)
    _set_session_cookie(response, session.id)
    return SessionInfo(
        employee_id=session.employee_id,
        employee_name=session.employee_name,
        role=session.role,
        tenant_name=session.tenant_name,
        expires_at=session.expires_at.isoformat(),
    )


@router.get("/session", response_model=SessionInfo)
async def session_info(session: AgentSession = Depends(get_current_session)):
    return SessionInfo(
        employee_id=session.employee_id,
        employee_name=session.employee_name,
        role=session.role,
        tenant_name=session.tenant_name,
        expires_at=session.expires_at.isoformat(),
    )


@router.post("/logout")
async def logout(request: Request, response: Response, db: DBSession = Depends(get_db)):
    settings = get_settings()
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if session_id:
        sessions.revoke_session(db, session_id)
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
    return {"detail": "Logged out"}
