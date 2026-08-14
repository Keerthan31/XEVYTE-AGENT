"""
E. EXECUTION PLANE — Error Recovery (spec section 22)

Categorizes every failure and maps it to an explicit strategy. tenacity
(in the underlying executor) already handles the low-level "retry a flaky
network call" mechanics; this module decides, at the RESULT level, what
the orchestrator should do NEXT — retry the whole step, ask the user,
refresh auth, escalate, or compensate — which tenacity's retry decorator
alone can't decide (it doesn't know the difference between a timeout and
a 403).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ErrorCategory(str, Enum):
    NETWORK = "NETWORK"
    TIMEOUT = "TIMEOUT"
    AUTHENTICATION = "AUTHENTICATION"
    AUTHORIZATION = "AUTHORIZATION"
    VALIDATION = "VALIDATION"
    BUSINESS = "BUSINESS"
    NOT_FOUND = "NOT_FOUND"
    SERVER_ERROR = "SERVER_ERROR"
    UNKNOWN = "UNKNOWN"


class Strategy(str, Enum):
    RETRY = "RETRY"
    DO_NOT_RETRY = "DO_NOT_RETRY"
    ASK_USER = "ASK_USER"
    REFRESH_AUTH = "REFRESH_AUTH"
    ESCALATE = "ESCALATE"
    COMPENSATE = "COMPENSATE"


_STRATEGY_MAP: dict[ErrorCategory, Strategy] = {
    ErrorCategory.NETWORK: Strategy.RETRY,
    ErrorCategory.TIMEOUT: Strategy.RETRY,
    ErrorCategory.AUTHENTICATION: Strategy.REFRESH_AUTH,
    ErrorCategory.AUTHORIZATION: Strategy.DO_NOT_RETRY,
    ErrorCategory.VALIDATION: Strategy.DO_NOT_RETRY,
    ErrorCategory.BUSINESS: Strategy.DO_NOT_RETRY,
    ErrorCategory.NOT_FOUND: Strategy.DO_NOT_RETRY,
    ErrorCategory.SERVER_ERROR: Strategy.ESCALATE,
    ErrorCategory.UNKNOWN: Strategy.ESCALATE,
}

_USER_FACING: dict[ErrorCategory, str] = {
    ErrorCategory.NETWORK: "I couldn't reach the HRMS system just now — trying again shortly usually fixes this.",
    ErrorCategory.TIMEOUT: "That request took too long to respond. Let me try again.",
    ErrorCategory.AUTHENTICATION: "Your session looks like it's expired — please log in again.",
    ErrorCategory.AUTHORIZATION: "You don't have permission for that action.",
    ErrorCategory.VALIDATION: "Something about the details provided doesn't look right for this action.",
    ErrorCategory.BUSINESS: "That couldn't go through — the system rejected it for a business reason.",
    ErrorCategory.NOT_FOUND: "I couldn't find that record.",
    ErrorCategory.SERVER_ERROR: "The HRMS system hit an internal error. This has been flagged for follow-up.",
    ErrorCategory.UNKNOWN: "Something unexpected went wrong and I couldn't complete this.",
}


@dataclass
class ErrorDecision:
    category: ErrorCategory
    strategy: Strategy
    user_message: str


def categorize(status_code: int | None, error_text: str | None) -> ErrorCategory:
    text = (error_text or "").lower()
    if status_code is None:
        if "timeout" in text:
            return ErrorCategory.TIMEOUT
        return ErrorCategory.NETWORK
    if status_code == 401:
        return ErrorCategory.AUTHENTICATION
    if status_code == 403:
        return ErrorCategory.AUTHORIZATION
    if status_code == 404:
        return ErrorCategory.NOT_FOUND
    if status_code == 422 or status_code == 400:
        return ErrorCategory.VALIDATION
    if status_code == 409:
        return ErrorCategory.BUSINESS
    if status_code and status_code >= 500:
        return ErrorCategory.SERVER_ERROR
    return ErrorCategory.UNKNOWN


def decide(status_code: int | None, error_text: str | None) -> ErrorDecision:
    category = categorize(status_code, error_text)
    return ErrorDecision(category=category, strategy=_STRATEGY_MAP[category], user_message=_USER_FACING[category])
