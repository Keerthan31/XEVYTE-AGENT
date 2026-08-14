"""
F. PLATFORM PLANE — Audit Logger (spec section 18/27)

Writes structured, immutable audit log records to the database for every
execution attempt in the enterprise pipeline.
"""
from __future__ import annotations

from typing import Any, Optional
from sqlalchemy.orm import Session as DBSession

from app.db_models import AuditLog
from app.guardrails.pii import redact


def log_execution(
    db: DBSession,
    *,
    session_id: Optional[str],
    conversation_id: Optional[str],
    employee_id: Optional[str],
    endpoint_id: str,
    http_method: str,
    path: str,
    risk_tier: str,
    user_confirmed: bool,
    request_arguments: dict[str, Any],
    response_status: Optional[int],
    response_body: Optional[Any],
    success: bool,
    error_message: Optional[str] = None,
) -> AuditLog:
    req_summary = redact(request_arguments) if isinstance(request_arguments, dict) else {}
    resp_summary = redact(response_body) if isinstance(response_body, (dict, list)) else {"raw": str(response_body)[:500]}

    entry = AuditLog(
        session_id=session_id,
        conversation_id=conversation_id,
        employee_id=employee_id,
        endpoint_id=endpoint_id,
        http_method=http_method,
        path=path,
        risk_tier=risk_tier,
        user_confirmed=user_confirmed,
        request_summary=req_summary,
        response_status=response_status,
        response_summary=resp_summary,
        success=success,
        error_message=error_message,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
