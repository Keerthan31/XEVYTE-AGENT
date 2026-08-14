"""
ORM models. Everything the agent needs to remember across requests lives
here: the (encrypted) HRMS bearer token per browser session, conversation
history, and a full audit trail of every endpoint call it ever makes —
required for anything touching payroll/PII in an HRMS.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AgentSession(Base):
    """One row per logged-in browser/agent session. Stores the Scaloz IAM
    JWT the user obtained through the real SSO flow — the agent never
    generates this token itself, only stores what SSO handed back."""
    __tablename__ = "agent_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    employee_id: Mapped[str] = mapped_column(String(128), nullable=True)
    employee_name: Mapped[str] = mapped_column(String(256), nullable=True)
    role: Mapped[str] = mapped_column(String(64), nullable=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=True)
    tenant_name: Mapped[str] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_sessions.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(256), default="New conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    session: Mapped["AgentSession"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | system
    content: Mapped[str] = mapped_column(Text)
    # Structured trace of what the agent decided/did for this turn (retrieved
    # endpoint candidates, chosen endpoint, risk tier, execution result) —
    # kept separately from `content` (the human-facing text) for debugging
    # and for the deepeval harness to replay real transcripts.
    trace: Mapped[dict] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class ApprovalRequest(Base):
    """Spec section 15 — Human Approval Service. One row per action that
    required explicit sign-off. Never execute an approval-required action
    before a matching APPROVED row exists here.

    action_hash (SHA-256 of tool_id + canonicalized arguments) binds the
    approval to the EXACT call that was shown to the approver — if the
    resolved arguments differ by even one field between approval time and
    execution time, the hash won't match and execution_gate.py rejects it.
    This is what stops an approved "delete category 77" from silently
    covering a re-planned "delete category 78"."""
    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_sessions.id"), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    tool_id: Mapped[str] = mapped_column(String(160), nullable=False)
    action_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_tier: Mapped[str] = mapped_column(String(24), nullable=False)
    encrypted_arguments: Mapped[str] = mapped_column(Text, nullable=True)  # Fernet encrypted real execution args (FIX 9)
    arguments_summary: Mapped[dict] = mapped_column(JSON, nullable=True)  # PII-redacted for display only
    policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")  # PENDING | APPROVED | REJECTED | EXPIRED
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    requester_employee_id: Mapped[str] = mapped_column(String(128), nullable=True)
    approver_employee_id: Mapped[str] = mapped_column(String(128), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, nullable=True)



class ParamProvenanceLog(Base):
    """Spec section 8/27 — every parameter resolution decision, for
    observability and post-hoc audit of exactly why a value was (or
    wasn't) trusted for a given tool call."""
    __tablename__ = "param_provenance_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    tool_id: Mapped[str] = mapped_column(String(160), nullable=False)
    param_name: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    trusted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EventLog(Base):
    """Spec section 21 — Event-driven agent. In-process event bus backing
    store (see app/planes/platform/event_bus.py). Swap for Kafka/RabbitMQ
    by replacing the publish/subscribe implementation behind the same
    interface; this table is the in-process default, not a Kafka
    replacement — see that module's docstring for why."""
    __tablename__ = "event_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=True)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PromptVersion(Base):
    """Spec section 26 — Prompt Registry."""
    __tablename__ = "prompt_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    prompt_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    environment: Mapped[str] = mapped_column(String(32), default="production")
    model: Mapped[str] = mapped_column(String(64), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    evaluation_score: Mapped[float] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")  # ACTIVE | ROLLED_BACK | DRAFT
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ModelGatewayCall(Base):
    """Spec section 25 — Model Gateway cost/latency/quality tracking."""
    __tablename__ = "model_gateway_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)  # "fast" | "reasoning" | "planner" | "responder"
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CircuitBreakerState(Base):
    """Spec section 17 — per-tool (really per-Java-controller) circuit
    breaker state, persisted so it survives restarts rather than resetting
    to closed every deploy."""
    __tablename__ = "circuit_breaker_state"

    tool_group: Mapped[str] = mapped_column(String(160), primary_key=True)  # module name, coarser than tool_id
    state: Mapped[str] = mapped_column(String(16), default="CLOSED")  # CLOSED | OPEN | HALF_OPEN
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class IdempotencyKey(Base):
    """Spec section 17 — write-operation idempotency protection. A retried
    write with the same key returns the original result instead of firing
    the Java API twice."""
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    tool_id: Mapped[str] = mapped_column(String(160), nullable=False)
    response_snapshot: Mapped[dict] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class WorkflowRun(Base):
    """Spec section 12 — Durable State. One row per user request as it
    moves through the pipeline. Actual step-level resumability (surviving
    a process restart mid-plan) is handled by LangGraph's Postgres
    checkpointer (app/workflow/state_machine.py, thread_id = this row's
    id) — this table is the fast, queryable "what state is request X in
    right now" view for observability/support, not a second persistence
    mechanism for the same data."""
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    employee_id: Mapped[str] = mapped_column(String(128), nullable=True)
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str] = mapped_column(String(64), nullable=True)
    domain: Mapped[str] = mapped_column(String(64), nullable=True)
    tool_id: Mapped[str] = mapped_column(String(160), nullable=True)
    # RECEIVED | UNDERSTANDING | WAITING_FOR_CLARIFICATION | PLANNING |
    # WAITING_FOR_APPROVAL | READY | EXECUTING | RETRYING | COMPLETED |
    # FAILED | ESCALATED  (see app/workflow/states.py for the enum)
    state: Mapped[str] = mapped_column(String(32), default="RECEIVED")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_category: Mapped[str] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class AuditLog(Base):
    """Immutable-in-practice record of every HRMS API call the agent made.
    Never store the bearer token or full request/response bodies verbatim
    here — see app/guardrails/pii.py for what gets redacted before a row
    is written."""
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_sessions.id"), nullable=True)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=True)
    employee_id: Mapped[str] = mapped_column(String(128), nullable=True)
    endpoint_id: Mapped[str] = mapped_column(String(160), nullable=False)
    http_method: Mapped[str] = mapped_column(String(8), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    risk_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    request_summary: Mapped[dict] = mapped_column(JSON, nullable=True)  # PII-redacted
    response_status: Mapped[int] = mapped_column(Integer, nullable=True)
    response_summary: Mapped[dict] = mapped_column(JSON, nullable=True)  # PII-redacted, truncated
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
