"""
D. GOVERNANCE/SAFETY PLANE — Approval Service (spec section 15)

Agent -> approval request -> user/authorized approver -> approve/reject ->
workflow resumes. Every request and decision is persisted in
approval_requests (db_models.py) — never in RAM only, so a pending
approval survives a process restart exactly like the rest of durable
state, and there's a permanent record of who approved what.

Every request is bound to an action_hash (SHA-256 of tool_id + the exact
resolved arguments). execution_gate.py re-derives this same hash right
before calling the API and refuses to proceed if it doesn't match the
approved one — an approval for "delete category 77" can never cover a
different call, even a same-tool one with different arguments.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.db_models import ApprovalRequest
from app.guardrails.pii import redact


def compute_action_hash(tool_id: str, arguments: dict[str, Any]) -> str:
    canonical = json.dumps({"tool_id": tool_id, "arguments": arguments}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _encrypt_arguments(arguments: dict[str, Any]) -> str:
    """Encrypt real execution arguments using Fernet for rest protection."""
    from app.auth.sessions import _fernet
    raw_json = json.dumps(arguments, default=str)
    return _fernet().encrypt(raw_json.encode()).decode()


def _decrypt_arguments(encrypted_str: str) -> dict[str, Any]:
    """Decrypt real execution arguments."""
    from app.auth.sessions import _fernet
    try:
        decrypted_bytes = _fernet().decrypt(encrypted_str.encode())
        return json.loads(decrypted_bytes.decode())
    except Exception:
        return {}


def request_approval(
    db: DBSession,
    *,
    session_id: str,
    conversation_id: str,
    tool_id: str,
    arguments: dict,
    risk_tier: str,
    policy_snapshot: dict,
    requester_employee_id: str | None = None,
) -> ApprovalRequest:
    req = ApprovalRequest(
        session_id=session_id,
        conversation_id=conversation_id,
        tool_id=tool_id,
        action_hash=compute_action_hash(tool_id, arguments),
        risk_tier=risk_tier,
        encrypted_arguments=_encrypt_arguments(arguments),
        arguments_summary=redact(arguments),
        policy_snapshot=policy_snapshot,
        requester_employee_id=requester_employee_id,
        status="PENDING",
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


def get_executable_arguments(db: DBSession, approval_id: str) -> dict[str, Any]:
    """FIX 9: Recover exact protected execution arguments. NEVER execute from
    arguments_summary if it contains redaction."""
    req = db.get(ApprovalRequest, approval_id)
    if not req or not req.encrypted_arguments:
        return req.arguments_summary if req and req.arguments_summary else {}
    return _decrypt_arguments(req.encrypted_arguments)


def decide(
    db: DBSession, approval_id: str, *, approved: bool, approver_employee_id: str, note: str | None = None
) -> ApprovalRequest | None:
    req = db.get(ApprovalRequest, approval_id)
    if not req or req.status != "PENDING":
        return None

    # FIX 10 / Self-approval safety: block self-approval for DESTRUCTIVE and HIGH_RISK_WRITE actions
    if approved and req.requester_employee_id and approver_employee_id == req.requester_employee_id:
        if req.risk_tier in ("DESTRUCTIVE", "HIGH_RISK_WRITE"):
            req.status = "REJECTED"
            req.decided_at = datetime.now(timezone.utc)
            req.approver_employee_id = approver_employee_id
            req.decision_note = "Self-approval blocked for high-risk/destructive actions."
            db.commit()
            db.refresh(req)
            return req

    req.status = "APPROVED" if approved else "REJECTED"
    req.decided_at = datetime.now(timezone.utc)
    req.approver_employee_id = approver_employee_id
    req.decision_note = note
    db.commit()
    db.refresh(req)
    return req


def is_approved(db: DBSession, approval_id: str) -> bool:
    req = db.get(ApprovalRequest, approval_id)
    return bool(req and req.status == "APPROVED")


def is_approved_for_action(
    db: DBSession,
    approval_id: str,
    tool_id: str,
    arguments: dict[str, Any],
    *,
    session_id: str | None = None,
    conversation_id: str | None = None,
) -> tuple[bool, str]:
    """FIX 10: Verifies APPROVED status, session/conversation binding, AND hash match."""
    req = db.get(ApprovalRequest, approval_id)
    if not req:
        return False, "approval not found"
    if req.status != "APPROVED":
        return False, f"approval status is {req.status}, not APPROVED"
    if session_id and req.session_id != session_id:
        return False, "approval belongs to a different session — session binding mismatch"
    if conversation_id and req.conversation_id != conversation_id:
        return False, "approval belongs to a different conversation — conversation binding mismatch"
    current_hash = compute_action_hash(tool_id, arguments)
    if current_hash != req.action_hash:
        return False, "action changed since approval was granted — hash mismatch, re-approval required"
    return True, "OK"


def get(db: DBSession, approval_id: str) -> ApprovalRequest | None:
    return db.get(ApprovalRequest, approval_id)

