import re
import logging

logger = logging.getLogger("xeva.auth.guardrails")

# Basic patterns to block
SUSPICIOUS_PATTERNS = [
    re.compile(r"ignore previous instructions", re.IGNORECASE),
    re.compile(r"system prompt", re.IGNORECASE),
    re.compile(r"you are now", re.IGNORECASE),
    re.compile(r"drop table", re.IGNORECASE),
    re.compile(r"select \* from", re.IGNORECASE),
    re.compile(r"<script>", re.IGNORECASE),
]

def check_input_safety(user_input: str) -> bool:
    """
    Layer 1 Guardrail: Fast regex-based safety check.
    Returns True if safe, False if potentially malicious.
    """
    if not user_input:
        return True
        
    for pattern in SUSPICIOUS_PATTERNS:
        if pattern.search(user_input):
            logger.warning(f"Guardrail triggered for pattern: {pattern.pattern}")
            return False
            
    return True

# Note: Layer 2 (LLM intent check) would typically be implemented as a lightweight
# LLM call before the main reasoning loop, but we will rely on the system prompt 
# instructions for this iteration to reduce latency.
