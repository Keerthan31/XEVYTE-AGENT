import json
import base64
import time
import hashlib
from cryptography.fernet import Fernet
import logging

from app.config import get_settings

logger = logging.getLogger("xeva.agent.confirmation")

# Create a stable Fernet key derived from JWT_SECRET for this session
_fernet = None

def _get_fernet():
    global _fernet
    if _fernet is None:
        settings = get_settings()
        # Derive a robust 32-byte key using SHA-256 digest
        secret = settings.JWT_SECRET.encode("utf-8")
        key_bytes = hashlib.sha256(secret).digest()
        key = base64.urlsafe_b64encode(key_bytes)
        _fernet = Fernet(key)
    return _fernet

def generate_confirmation_token(action_data: dict, employee_id: str) -> str:
    """
    Encrypts the action details into a token that the frontend can pass back
    when the user clicks 'Approve'.
    """
    payload = {
        "action": action_data,
        "employee_id": employee_id,
        "exp": int(time.time()) + 3600 # 1 hour expiry
    }
    
    payload_bytes = json.dumps(payload).encode('utf-8')
    token = _get_fernet().encrypt(payload_bytes).decode('utf-8')
    return token

def verify_confirmation_token(token: str, employee_id: str) -> dict:
    """
    Decrypts the token and verifies it hasn't expired and belongs to the user.
    Returns the action_data dict if valid.
    """
    try:
        payload_bytes = _get_fernet().decrypt(token.encode('utf-8'))
        payload = json.loads(payload_bytes.decode('utf-8'))
        
        if payload.get("exp", 0) < time.time():
            raise ValueError("Confirmation token expired")
            
        if payload.get("employee_id") != employee_id:
            raise ValueError("Token does not belong to this user")
            
        return payload.get("action", {})
        
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Invalid confirmation token: {e}")
        raise ValueError(f"Invalid confirmation token: {str(e)}")
