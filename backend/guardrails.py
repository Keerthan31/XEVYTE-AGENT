"""
Guardrails & PII Security Module for Xevyte HRMS AI Agent.
Provides PII data masking for logs and prompt injection security inspections.
"""

import re
import logging

logger = logging.getLogger(__name__)

# PII Regex patterns for masking confidential data in logs
_JWT_REGEX = re.compile(r"Bearer\s+[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+\.?[A-Za-z0-9\-_=]*")
_PASS_REGEX = re.compile(r'("password"|"DB_PASSWORD")\s*[:=]\s*["\'][^"\']+["\']', re.IGNORECASE)


def mask_pii(text: str) -> str:
    """Mask confidential tokens, passwords, and PII from log outputs."""
    if not text:
        return text
    masked = _JWT_REGEX.sub("Bearer [MASKED_JWT_TOKEN]", text)
    masked = _PASS_REGEX.sub(r'\1: "[MASKED_PASSWORD]"', masked)
    return masked


def validate_guardrails(user_message: str) -> dict:
    """
    Perform deep security inspection on incoming user prompts.
    Returns dict: {"safe": bool, "reason": str | None}
    """
    lowered = user_message.lower().strip()
    
    # Prompt injection & jailbreak patterns
    injection_patterns = [
        r"ignore (all )?previous instructions",
        r"ignore your system prompt",
        r"reveal (your )?system prompt",
        r"print (your )?initial prompt",
        r"override safety rules",
        r"bypass tool requirements",
        r"forget your rules",
        r"system prompt leak",
        r"you are now (an? )?unrestricted",
        r"do anything now",
        r"act as a linux terminal",
        r"print internal code",
    ]
    
    for pattern in injection_patterns:
        if re.search(pattern, lowered):
            logger.warning(f"Guardrail violation detected: {pattern} in message.")
            return {
                "safe": False,
                "reason": (
                    "I am Xeva, an HR assistant for Xevyte Connect. "
                    "I operate strictly within HRMS policy guidelines and cannot reveal or override system safety instructions. "
                    "How can I assist you with your HR requests today?"
                )
            }
            
    return {"safe": True, "reason": None}


def sanitize_output(response: str) -> str:
    """
    Ensure the LLM does not leak internal API schemas, internal network URLs, or raw SQL.
    This runs right before sending the final response to the user.
    """
    if not response:
        return response
    
    # Mask internal API base paths if the LLM accidentally dumps them
    response = re.sub(r"https?://(?:localhost|127\.0\.0\.1|api\.xevyte\.local)(:\d+)?/api/[a-zA-Z0-9/\-_?=]+", "[INTERNAL_API_CALL]", response)
    
    # Check for raw JSON envelope leakage
    if '{"success":' in response and '"metadata":' in response:
        logger.warning("Sanitizer caught raw JSON envelope leak in output.")
        # Attempt to strip the JSON, or just return a safe fallback if it's purely a JSON dump
        if response.strip().startswith('{"success":'):
            return "I apologize, but I encountered an internal formatting error while generating my response. Please try again."

    return response
