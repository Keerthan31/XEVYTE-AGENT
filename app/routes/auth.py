from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import datetime

from app.auth.jwt_handler import validate_and_extract_token

router = APIRouter()

class TokenRequest(BaseModel):
    token: str

@router.post("/auth/token")
async def exchange_token(request: TokenRequest):
    """Exchanges a Scaloz JWT token for an agent session."""
    user_context = validate_and_extract_token(request.token)
    if not user_context:
        raise HTTPException(status_code=401, detail="Invalid token")
        
    return {
        "employee_id": user_context["employeeId"],
        "employee_name": user_context["name"],
        "role": user_context["role"],
        "tenant_name": user_context["tenant"],
        "expires_at": (datetime.datetime.utcnow() + datetime.timedelta(hours=24)).isoformat()
    }
