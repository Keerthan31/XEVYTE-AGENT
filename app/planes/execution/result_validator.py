"""
E. EXECUTION PLANE — Result Validator (spec section 18)

    "Never assume a Java API result is valid. Normalize all Java
    responses into a standard internal format."

Every response from api_fabric.py — success or failure — is normalized
into the exact envelope shape the spec requires before anything downstream
(the Response Generator) is allowed to read it. This is what "the
response generator must use validated results only" actually means in
code: response_generator.py physically cannot see the raw executor output,
only this envelope.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class NormalizedResult:
    success: bool
    data: Optional[Any]
    error: Optional[str]
    tool_id: str
    request_id: str
    timestamp: str
    status_code: Optional[int] = None
    idempotent_replay: bool = False
    circuit_breaker: Optional[str] = None
    error_category: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "tool_id": self.tool_id,
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "status_code": self.status_code,
            "error_category": self.error_category,
        }


def _classify_error(status_code: Optional[int], err_msg: Optional[str]) -> Optional[str]:
    if not err_msg and (status_code is None or (200 <= status_code < 300)):
        return None
    if status_code:
        if 400 <= status_code < 500:
            return f"HTTP_{status_code}"
        elif status_code >= 500:
            return f"HTTP_{status_code}"
    if err_msg:
        msg = err_msg.lower()
        if "timeout" in msg:
            return "TIMEOUT"
        if "network" in msg or "connect" in msg:
            return "CONNECTION_FAILURE"
        if "missing" in msg:
            return "MISSING_PARAMETERS"
        if "authorization" in msg or "forbidden" in msg:
            return "AUTHORIZATION_DENIED"
    return "UNKNOWN_FAILURE"


def normalize(tool_id: str, raw: dict) -> NormalizedResult:
    """raw is api_fabric.execute_with_fabric()'s return shape:
    {status_code, ok, body, error, latency_ms, [idempotent_replay], [circuit_breaker]}."""
    ok = bool(raw.get("ok"))
    body = raw.get("body") if ok else None
    err = None if ok else (raw.get("error") or "unknown error")
    status = raw.get("status_code")
    category = _classify_error(status, err)

    return NormalizedResult(
        success=ok,
        data=body,
        error=err,
        tool_id=tool_id,
        request_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        status_code=status,
        idempotent_replay=bool(raw.get("idempotent_replay")),
        circuit_breaker=raw.get("circuit_breaker"),
        error_category=category,
    )


def validate_shape(data: Any) -> bool:
    """Coarse sanity check that a 'successful' response body isn't
    obviously wrong (empty when data was expected, or an HTML error page
    that slipped through with a 200). Real per-endpoint response schemas
    aren't uniformly declared in the Java controllers (see
    tool_registry.py's response_schema=None note) so this stays a shape
    check, not strict schema validation — strict validation happens on
    the way IN (validation.py) where the schema really is known."""
    if data is None:
        return False
    if isinstance(data, str) and data.strip().lower().startswith(("<html", "<!doctype")):
        return False
    return True
