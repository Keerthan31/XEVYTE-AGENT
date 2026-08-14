"""LangGraph state — the single object threaded through every node."""
from __future__ import annotations

from typing import Any, Literal, Optional, TypedDict


class RetrievedCandidate(TypedDict):
    endpoint_id: str
    score: float


class PlannedCall(TypedDict, total=False):
    endpoint_id: str
    path_args: dict[str, str]
    query_args: dict[str, str]
    body: Any
    missing_info: list[str]
    confidence: float


class ExecutionResult(TypedDict, total=False):
    status_code: int
    ok: bool
    body: Any
    error: Optional[str]
    latency_ms: int


class AgentState(TypedDict, total=False):
    # ---- input ----
    user_message: str
    conversation_history: list[dict]  # [{"role": "user"|"assistant", "content": str}, ...]
    bearer_token: str
    employee_id: Optional[str]
    role: Optional[str]

    # ---- pipeline ----
    input_warnings: list[str]
    retrieved: list[RetrievedCandidate]
    planned_call: Optional[PlannedCall]
    risk_tier: Optional[str]
    needs_confirmation: bool
    cross_identity_note: Optional[str]
    execution: Optional[ExecutionResult]

    # ---- output ----
    status: Literal["completed", "needs_confirmation", "needs_info", "error"]
    reply: str
