"""
Redacts sensitive values before anything gets written to the audit log,
LangSmith traces, or conversation `trace` JSON. This runs on OUTBOUND
logging only — it never touches what's actually sent to the HRMS API,
only what gets *persisted about* that call.
"""
from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEY_PATTERNS = re.compile(
    r"(password|pan|aadhaar|aadhar|ssn|bank[_a-z]*account|accountno|ifsc|"
    r"salary|ctc|token|secret|authorization|otp|cvv|cardnumber)",
    re.IGNORECASE,
)

MASK = "***REDACTED***"


def redact(value: Any, _depth: int = 0) -> Any:
    if _depth > 6:  # guard against pathological nesting
        return MASK
    if isinstance(value, dict):
        return {
            k: (MASK if SENSITIVE_KEY_PATTERNS.search(str(k)) else redact(v, _depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v, _depth + 1) for v in value[:50]]  # cap list length in logs
    if isinstance(value, str) and len(value) > 4000:
        return value[:4000] + "...[truncated]"
    return value


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k: (MASK if k.lower() in ("authorization", "cookie", "set-cookie") else v) for k, v in headers.items()}
