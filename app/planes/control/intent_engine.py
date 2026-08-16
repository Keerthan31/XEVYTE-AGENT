"""
B.3.1 INTENT ENGINE (spec section 2)

    "The Intent Engine must return structured output ... Do not allow
    free-form intent output. If intent confidence is below the configured
    threshold, do not execute a tool. Ask a clarification question
    instead."

Uses instructor (already in the stack for the planner) for the same
reason: intent classification driving a downstream tool call needs a
strictly-typed result, not free text to parse hopefully.
"""
from __future__ import annotations

from typing import Optional, Dict

from pydantic import BaseModel, Field

from app.agent.llm import get_instructor_client
from app.config import get_settings
from app.planes.control.domain_router import Domain

CONFIDENCE_THRESHOLD = 0.40

INTENT_SYSTEM_PROMPT = """Classify the user's HR/HRMS-related message into a structured intent. Return:
- intent: a short UPPER_SNAKE_CASE label for what they want (e.g. APPLY_LEAVE, VIEW_PAYSLIP, DELETE_ASSET_CATEGORY,
  RAISE_TICKET, CHECK_LEAVE_BALANCE). Invent a reasonable label if nothing obvious fits — never leave it empty.
- domain: your best guess at which business domain this belongs to, from the given list. Use UNKNOWN if genuinely
  unclear rather than guessing one that doesn't fit.
- entities: any concrete values mentioned (dates, names, amounts, ids, categories) as a flat dict.
- confidence: 0-1, how confident you are this classification is correct given ONLY the message (not the tool catalog
  — you have not seen it). Lower confidence only for truly vague or contradictory messages. Ordinary HR requests
  like "apply leave tomorrow" or "show my payslip" should score >= 0.7.
- ambiguities: short list of what's unclear, if anything (empty list if nothing is ambiguous).
Do not invent entity values that aren't stated or clearly implied — omit uncertain ones rather than guessing.
If the user is answering a prior clarification (short replies with dates/types/ids), keep confidence high and
classify entities from that answer — do not ask again unnecessarily."""


class IntentResult(BaseModel):
    intent: str
    domain: str = Field(description="One of the known domain names, or UNKNOWN")
    entities: dict = Field(default_factory=dict, description="Dictionary of extracted entities")
    confidence: float = Field(ge=0.0, le=1.0)
    ambiguities: list[str] = Field(default_factory=list)


def classify(user_message: str, conversation_history: list[dict] | None = None) -> IntentResult:
    settings = get_settings()
    domain_list = ", ".join(d.value for d in Domain)
    history_block = ""
    if conversation_history:
        history_block = "\n\nRecent conversation:\n" + "\n".join(
            f"{m['role']}: {m['content']}" for m in conversation_history[-4:]
        )
    client = get_instructor_client()
    return client.chat.completions.create(
        model=settings.PLANNER_MODEL,
        response_model=IntentResult,
        max_retries=2,
        messages=[
            {"role": "system", "content": INTENT_SYSTEM_PROMPT + f"\n\nKnown domains: {domain_list}"},
            {"role": "user", "content": f"Message: {user_message}{history_block}"},
        ],
    )


def needs_clarification(result: IntentResult) -> bool:
    return result.confidence < CONFIDENCE_THRESHOLD


def clarification_question(result: IntentResult) -> str:
    if result.ambiguities:
        return "Could you clarify: " + "; ".join(result.ambiguities) + "?"
    return "I want to make sure I get this right — could you rephrase what you'd like me to do?"
