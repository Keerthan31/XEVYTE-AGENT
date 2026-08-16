"""
Agent session lifecycle: encrypts the Scaloz IAM token at rest in Postgres
(SESSION_SECRET_KEY, unrelated to the HRMS backend's own JWT_SECRET —
this key only protects the agent's local copy of an already-issued token)
and provides lookup/expiry/revocation.
"""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session as DBSession

from app.auth.sso import decode_jwt_claims_unverified, verify_jwt_and_decode
from app.config import get_settings
from app.db_models import AgentSession


def _fernet() -> Fernet:
    settings = get_settings()
    secret_key = settings.SESSION_SECRET_KEY
    if not secret_key:
        iam_url = settings.SCALOZ_IAM_URL.lower()
        if "localhost" in iam_url or "127.0.0.1" in iam_url or "workspacetest" in iam_url:
            secret_key = "xevyte_agent_default_secret_key_for_testing_and_local_dev"
        else:
            raise ValueError(
                "SESSION_SECRET_KEY must be set in production to encrypt session tokens at rest. "
                "Set a secure key in your .env file."
            )
    digest = hashlib.sha256(secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))



def create_session(db: DBSession, token: str) -> AgentSession:
    settings = get_settings()
    claims = verify_jwt_and_decode(token)
    exp = claims.get("exp")
    expires_at = (
        datetime.fromtimestamp(exp, tz=timezone.utc)
        if exp
        else datetime.now(timezone.utc) + timedelta(hours=settings.SESSION_TTL_HOURS)
    )
    
    employee_id = claims.get("employeeId") or claims.get("sub")

    # If cookies are blocked by the browser (CORS), every request falls back to the Bearer token.
    # To prevent creating a new AgentSession (and thus breaking Conversation links) on every request,
    # we first check if there's an active session for this employee.
    existing = db.query(AgentSession).filter(
        AgentSession.employee_id == employee_id,
        AgentSession.revoked == False,
        AgentSession.expires_at > datetime.now(timezone.utc)
    ).order_by(AgentSession.created_at.desc()).first()
    
    if existing:
        return existing

    session = AgentSession(
        encrypted_token=_fernet().encrypt(token.encode()).decode(),
        employee_id=employee_id,
        employee_name=claims.get("name"),
        role=claims.get("role"),
        tenant_id=claims.get("tenantId"),
        tenant_name=claims.get("tenantName"),
        expires_at=expires_at,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db: DBSession, session_id: str) -> Optional[AgentSession]:
    session = db.get(AgentSession, session_id)
    if not session or session.revoked:
        return None
    if session.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        return None
    return session


def get_bearer_token(session: AgentSession) -> Optional[str]:
    try:
        return _fernet().decrypt(session.encrypted_token.encode()).decode()
    except InvalidToken:
        return None


def revoke_session(db: DBSession, session_id: str) -> None:
    session = db.get(AgentSession, session_id)
    if session:
        session.revoked = True
        db.commit()
