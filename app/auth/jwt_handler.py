import logging
from typing import Dict, Any, Optional
import jwt

from app.config import get_settings

logger = logging.getLogger("xeva.auth.jwt")

def validate_and_extract_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Validates a JWT token from Scaloz IAM and extracts user claims.
    """
    if not token:
        return None
        
    if token.startswith("Bearer "):
        token = token[7:]
        
    settings = get_settings()
    
    try:
        # Validate the token using the shared JWT_SECRET
        payload = jwt.decode(
            token, 
            settings.JWT_SECRET, 
            algorithms=["HS256"]
            # options={"verify_iss": True, "issuer": settings.jwt_issuer} # Uncomment if issuer is strictly enforced
        )
        
        # Extract required claims
        user_data = {
            "employeeId": payload.get("employeeId"),
            "tenant": payload.get("tenant"),
            "role": payload.get("role", "USER"),
            "name": payload.get("name", "User"),
            "sub": payload.get("sub"), # Username/Email
        }
        
        if not user_data["employeeId"]:
            logger.warning("Token validated but missing employeeId claim")
            return None
            
        return user_data
        
    except jwt.ExpiredSignatureError:
        logger.warning("Token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid token: {e}")
        return None
    except Exception as e:
        logger.error(f"JWT Validation error: {e}")
        return None
