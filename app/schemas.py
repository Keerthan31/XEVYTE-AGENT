"""Pydantic schemas for the agent's own FastAPI surface (not to be confused
with the HRMS endpoint catalog schemas in app/catalog)."""
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------- auth ----
class LoginStartResponse(BaseModel):
    sso_redirect_url: str


class SSOCallbackResult(BaseModel):
    session_id: str
    employee_id: Optional[str] = None
    employee_name: Optional[str] = None
    role: Optional[str] = None
    tenant_name: Optional[str] = None
    expires_at: str


class SessionInfo(BaseModel):
    employee_id: Optional[str]
    employee_name: Optional[str]
    role: Optional[str]
    tenant_name: Optional[str]
    expires_at: str


# ---------------------------------------------------------------- chat ----
class ChatRequest(BaseModel):
    model_config = {"extra": "ignore"}
    message: str = Field(..., min_length=1, max_length=8000)
    conversation_id: Optional[str] = None


class EndpointCallSummary(BaseModel):
    endpoint_id: str
    http_method: str
    path: str
    module: str
    risk_tier: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    status: Literal[
        "completed",
        "needs_confirmation",
        "needs_info",
        "needs_clarification",
        "capability_not_available",
        "error",
    ]
    candidate_call: Optional[EndpointCallSummary] = None
    pending_confirmation_token: Optional[str] = None
    missing_info: list[str] = []
    raw_result: Optional[Any] = None


class ConfirmRequest(BaseModel):
    conversation_id: str
    pending_confirmation_token: str
    approve: bool


# ------------------------------------------------------------- catalog ----
class CatalogRefreshResponse(BaseModel):
    endpoints_discovered: int
    modules: int
    chunks_ingested: int


class CatalogEndpointOut(BaseModel):
    id: str
    module: str
    http_method: str
    path: str
    description: str
    auth_required: bool
    destructive_hint: bool
    sensitive_module_hint: bool
