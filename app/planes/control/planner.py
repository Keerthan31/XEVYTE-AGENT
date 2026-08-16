"""
B.3.6 PLANNER (spec section 11)

Picks one tool_id from the hybrid-discovery candidate list and extracts
its parameters as LLMExtractedParam objects — each with a claimed source
(USER/SESSION/API_RESULT/MEMORY/SYSTEM/LLM_GUESS) and the literal text
grounding that claim. This is the ONLY place an LLM proposes parameter
values; context_engine.py independently cross-checks every claim before
anything becomes "trusted" and executable. The planner's own confidence
self-report is informational — it does not grant anything a pass past the
Missing Parameter Gate or Execution Gate.

Also classifies the step as read/write/destructive (mirrors risk_engine's
tiers at the planning stage, before a Tool Registry lookup even happens)
so the orchestrator can short-circuit obviously-wrong plans early.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.agent.llm import get_instructor_client
from app.config import get_settings
from app.planes.control.context_engine import LLMExtractedParam
from app.planes.control.intent_engine import IntentResult
from app.planes.control.tool_discovery import Candidate
from app.planes.knowledge.tool_registry import ToolRegistryEntry

PLANNER_SYSTEM_PROMPT = """You are the planning stage of an HRMS agent. You're given the user's message, their \
classified intent, conversation history, and a short list of CANDIDATE tools (already retrieved — you are \
choosing among these, not the full API). Decide:

1. Which ONE candidate tool_id best satisfies the request — "" if genuinely none fit.
2. For EACH parameter that tool needs (only the ones its contract actually lists), produce a value AND a source:
   - USER: grounded in the current message — quote_or_basis must be the actual phrase driving it
   - SESSION: the logged-in employee's own id/role/tenant — quote_or_basis can be empty
   - API_RESULT: came from a prior tool result shown to you this conversation — quote_or_basis empty
   - MEMORY: came from approved long-term memory shown to you — quote_or_basis empty
   - LLM_GUESS: you don't actually have grounding — use this rather than picking SESSION/API_RESULT/USER
     when you're not sure; a wrongly-claimed source is worse than an honest guess, both get treated as missing,
     but a false claim of a trusted source is a bigger problem if it were ever wrong.
3. Fields you have no basis for at all: simply omit them — do not include a low-confidence guess as USER/SESSION.

Never invent ids, dates, or amounts that aren't grounded in something shown to you. When genuinely unsure, prefer
omitting the parameter (it will correctly show up as needing clarification) over guessing.
IMPORTANT: Format dates using each field's wire_format when listed (e.g. Leave startDate/endDate use dd-MM-yyyy).
If no wire_format is listed, use YYYY-MM-DD. Accept either style from the user and convert before emitting."""


class PlannedParam(BaseModel):
    name: str
    value: str
    claimed_source: str = Field(description="USER | SESSION | API_RESULT | MEMORY | LLM_GUESS")
    quote_or_basis: str = ""


class PlanResult(BaseModel):
    tool_id: str
    step_type: str = Field(description="READ | WRITE | DESTRUCTIVE")
    parameters: list[PlannedParam] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


def _candidate_block(c: Candidate) -> str:
    t = c.tool
    lines = [f"tool_id: {t.tool_id}", f"  {t.http_method} {t.endpoint}  (module: {t.module}, risk: {t.risk_level.value})",
              f"  {t.description}"]
    all_params = t.required_parameters + t.optional_parameters
    if all_params:
        lines.append("  parameters: " + ", ".join(f"{p['name']}({p.get('java_type','?')}{'*' if p in t.required_parameters else ''})" for p in all_params))
    if t.request_schema:
        lines.append("  body fields: " + ", ".join(f["name"] for f in t.request_schema[:10]))
    return "\n".join(lines)


def plan(
    user_message: str,
    intent: IntentResult,
    candidates: list[Candidate],
    conversation_history: list[dict] | None = None,
    employee_id: Optional[str] = None,
    role: Optional[str] = None,
) -> PlanResult:
    settings = get_settings()
    history_block = ""
    if conversation_history:
        history_block = "\n\nRecent conversation:\n" + "\n".join(
            f"{m['role']}: {m['content']}" for m in conversation_history[-4:]
        )
    candidates_block = "\n\n".join(_candidate_block(c) for c in candidates)

    user_prompt = (
        f"User message: {user_message}\n"
        f"Classified intent: {intent.intent} (domain={intent.domain}, entities={intent.entities})\n"
        f"Logged-in session: employee_id={employee_id!r}, role={role!r}\n"
        f"{history_block}\n\n"
        f"Candidate tools:\n{candidates_block}"
    )
    client = get_instructor_client()
    return client.chat.completions.create(
        model=settings.PLANNER_MODEL,
        response_model=PlanResult,
        max_retries=2,
        messages=[
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )


def to_extracted_params(plan_result: PlanResult) -> list[LLMExtractedParam]:
    from app.planes.control.context_engine import ParamSource
    out = []
    for p in plan_result.parameters:
        try:
            source = ParamSource(p.claimed_source.upper())
        except ValueError:
            source = ParamSource.LLM_GUESS
        out.append(LLMExtractedParam(name=p.name, value=p.value, claimed_source=source, quote_or_basis=p.quote_or_basis))
    return out
