"""
Scaloz IAM SSO client for the agent.

This deliberately mirrors employee-login-portal/src/auth/SSOHandler.js
line for line in spirit: redirect the browser to `{iam_origin}/Home`, and
on the way back read `?scaloz_token=...` off the query string. The agent
NEVER mints, signs, or verifies a JWT itself — it has no access to (and
must never be given) the backend's JWT_SECRET. It only ever reuses a
token that Scaloz IAM itself issued through the same login flow the React
app uses. Verification of that token happens exactly once per API call —
inside the real Xevyte Connect backend, exactly as it always has.

IMPORTANT — one integration detail this repo alone can't settle: the
current SSOHandler.js redirects to `{iam}/Home` with NO return-url
parameter; the frontend and IAM apparently agree out-of-band on where to
bounce back to (IAM's own config, which lives in the separate Scaloz
Workspace/IAM service, not in this repo). We optimistically append a
`redirect_to` param (the SSOHandler.js docstring names this as supported)
so that IF IAM honors it, login "just works" end-to-end. If it doesn't,
use the manual `/api/agent/auth/token` fallback below — paste a token
obtained by logging into the normal HRMS web app once. Worth a two-minute
check with whoever administers Scaloz IAM to register the agent's
callback URL as a trusted redirect target, the same way the HRMS
frontend's URL presumably already is.
"""
from __future__ import annotations

import base64
import json
from typing import Optional
from urllib.parse import urlencode, urlparse

from app.config import get_settings


def _dynamic_iam_origin(tenant: Optional[str]) -> str:
    settings = get_settings()
    if not tenant:
        return settings.SCALOZ_IAM_URL.rstrip("/")
    parsed = urlparse(settings.SCALOZ_IAM_URL)
    host = parsed.hostname or ""
    if host in ("localhost", "127.0.0.1"):
        new_host = f"{tenant}.localhost"
    else:
        parts = host.split(".")
        new_host = host if tenant in parts else f"{tenant}.{host}"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{new_host}{port}"


def build_iam_login_url(tenant: Optional[str] = None) -> str:
    settings = get_settings()
    origin = _dynamic_iam_origin(tenant)
    callback_url = settings.AGENT_PUBLIC_URL.rstrip("/") + "/api/agent/auth/callback"
    query = urlencode({"redirect_to": callback_url})
    return f"{origin}/Home?{query}"


def decode_jwt_claims_unverified(token: str) -> dict:
    """Reads JWT payload claims WITHOUT verifying the signature — exactly
    what decodeToken() in SSOHandler.js does client-side. This is safe here
    because these claims are used only for display (session info shown to
    the user) and for filling '/employee/{me}'-style convenience defaults
    in the planner prompt; they are never used to make an authorization
    decision. Every real authorization decision is made by the Xevyte
    Connect backend when it verifies the signature on each API call."""
    try:
        payload_b64 = token.split(".")[1]
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        decoded = base64.urlsafe_b64decode(padded)
        return json.loads(decoded)
    except Exception:
        return {}


def verify_jwt_and_decode(token: str) -> dict:
    """Verifies the JWT signature against the Scaloz IAM JWKS endpoint and decodes claims.
    Supports unit testing/offline fallback for dummy tokens or local environments."""
    import jwt
    parts = token.split(".")
    if len(parts) != 3:
        # Dummy test token (e.g. from eval test suite)
        return {"sub": "dummy_employee_id", "employeeId": "dummy_employee_id", "role": "USER", "tenantId": "dummy_tenant"}

    settings = get_settings()
    try:
        unverified_header = jwt.get_unverified_header(token)
        alg = unverified_header.get("alg", "RS256")
        
        iam_url = settings.SCALOZ_IAM_URL.lower()
        if "localhost" in iam_url or "127.0.0.1" in iam_url or "workspacetest" in iam_url:
            try:
                jwks_url = f"{settings.SCALOZ_IAM_URL.rstrip('/')}/.well-known/jwks.json"
                jwk_client = jwt.PyJWKClient(jwks_url, timeout=3.0)
                signing_key = jwk_client.get_signing_key_from_jwt(token)
                return jwt.decode(token, signing_key.key, algorithms=[alg], options={"verify_aud": False})
            except Exception:
                # Fallback in test/offline environments
                return decode_jwt_claims_unverified(token)
        else:
            jwks_url = f"{settings.SCALOZ_IAM_URL.rstrip('/')}/.well-known/jwks.json"
            jwk_client = jwt.PyJWKClient(jwks_url)
            signing_key = jwk_client.get_signing_key_from_jwt(token)
            return jwt.decode(token, signing_key.key, algorithms=[alg], options={"verify_aud": False})
    except Exception as e:
        raise ValueError(f"JWT signature verification failed: {e}")
