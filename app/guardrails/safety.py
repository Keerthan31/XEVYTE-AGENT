"""
Lightweight safety heuristics that sit around the LLM calls. These are
deliberately simple pattern checks, not a substitute for the risk-tiering
in app/guardrails/risk.py — they catch a different failure mode: the model
being steered off-task by injected text, and actions silently targeting
someone other than the logged-in employee.
"""
from __future__ import annotations

import re

INJECTION_MARKERS = re.compile(
    r"(ignore (all|previous|the) instructions|disregard (all|previous) instructions|"
    r"you are now|new system prompt|reveal your (system )?prompt|print your instructions|"
    r"act as (root|admin|system)|<\s*system\s*>)",
    re.IGNORECASE,
)

TOKEN_EXFIL_MARKERS = re.compile(
    r"(bearer\s+[a-z0-9\-_.]{20,}|what('|'| i)?s my token|show me the (jwt|bearer|auth) token|"
    r"print (the|my) (access|bearer|auth) token)",
    re.IGNORECASE,
)


def scan_user_input(text: str) -> list[str]:
    """Returns a list of warning tags (empty if nothing notable). Used to
    bump logging verbosity and, for TOKEN_EXFIL, to hard-block the turn —
    the agent should never echo the raw bearer token back into chat."""
    warnings = []
    if INJECTION_MARKERS.search(text):
        warnings.append("possible_prompt_injection")
    if TOKEN_EXFIL_MARKERS.search(text):
        warnings.append("token_exfiltration_attempt")
    if len(text) > 6000:
        warnings.append("unusually_long_input")
    return warnings


def scan_tool_output(text: str) -> list[str]:
    """Defense in depth: HRMS API responses echo back user-authored fields
    (grievance text, ticket descriptions, employee names). Flag anything
    that looks like it's trying to redirect the agent's next action —
    the planner prompt treats retrieved API data as data, never as
    instructions, but this gives us a signal to log/alert on regardless."""
    warnings = []
    if INJECTION_MARKERS.search(text):
        warnings.append("possible_injection_in_api_response")
    return warnings


def check_cross_identity(session_employee_id: str | None, path_args: dict, query_args: dict) -> str | None:
    """If the call targets an employeeId/userId different from the logged-in
    user, return a human-readable note to surface in the confirmation
    prompt (managers/HR legitimately act on others' records — this isn't a
    block, just transparency about whose record is being touched)."""
    if not session_employee_id:
        return None
    candidates = {**path_args, **query_args}
    for key in ("employeeId", "userId", "empId", "managerId", "hrId"):
        val = candidates.get(key)
        if val and str(val) != str(session_employee_id):
            return f"This action targets employee '{val}', not your own record ('{session_employee_id}')."
    return None
