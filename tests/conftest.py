"""
Shared pytest fixtures for the XEVYTE-AGENT test suite.
Provides: JWT tokens, user contexts, mock DB sessions, test client, catalog access,
and custom asyncio test runner hook.
"""

import os
import sys
import json
import time
import inspect
import asyncio
import pytest
import jwt
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any

# ---------------------------------------------------------------------------
# Ensure the project root is importable
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Constants (mirror .env for testing – NO live secrets leak)
# ---------------------------------------------------------------------------
TEST_JWT_SECRET = "G7vQ2mX9kL4pR8sT1wN6yH3cD5fJ0zAa"
TEST_JAVA_BACKEND_URL = "http://localhost:8082"
CATALOG_PATH = os.path.join(PROJECT_ROOT, "config", "XEVYTE_API_CATALOG.json")

os.environ["JWT_SECRET"] = TEST_JWT_SECRET
os.environ["OPENAI_API_KEY"] = "sk-test-fake-key"
os.environ["JAVA_BACKEND_URL"] = TEST_JAVA_BACKEND_URL
os.environ["HRMS_API_BASE_URL"] = TEST_JAVA_BACKEND_URL


# ============================================================================
# Asyncio Hook for Async Tests
# ============================================================================

def pytest_pyfunc_call(pyfuncitem):
    """Enable running async test functions directly without external plugin dependency."""
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            testargs = {
                arg: pyfuncitem.funcargs[arg]
                for arg in pyfuncitem._fixtureinfo.argnames
            }
            loop.run_until_complete(pyfuncitem.obj(**testargs))
        finally:
            loop.close()
        return True
    return None


# ============================================================================
# JWT Token Fixtures
# ============================================================================

def _make_token(claims: dict, secret: str = TEST_JWT_SECRET, expired: bool = False) -> str:
    """Create a signed JWT with given claims."""
    payload = {**claims}
    if expired:
        payload["exp"] = int(time.time()) - 3600  # 1 hour in the past
    else:
        payload["exp"] = int(time.time()) + 3600  # 1 hour in the future
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture
def employee_claims() -> Dict[str, Any]:
    return {
        "sub": "john.doe@xevyte.com",
        "employeeId": "EMP001",
        "tenant": "scaloz",
        "tenantId": "scaloz",
        "role": "EMPLOYEE",
        "name": "John Doe",
        "department": "Engineering",
        "reportingManager": "MGR001",
    }


@pytest.fixture
def manager_claims() -> Dict[str, Any]:
    return {
        "sub": "jane.mgr@xevyte.com",
        "employeeId": "MGR001",
        "tenant": "scaloz",
        "tenantId": "scaloz",
        "role": "MANAGER",
        "name": "Jane Manager",
        "department": "Engineering",
    }


@pytest.fixture
def admin_claims() -> Dict[str, Any]:
    return {
        "sub": "scaloz_admin",
        "employeeId": "scaloz_admin",
        "tenant": "scaloz",
        "tenantId": "scaloz",
        "role": "ADMIN",
        "name": "Admin User",
        "department": "Admin",
    }


@pytest.fixture
def hr_claims() -> Dict[str, Any]:
    return {
        "sub": "hr.user@xevyte.com",
        "employeeId": "HR001",
        "tenant": "scaloz",
        "tenantId": "scaloz",
        "role": "HR",
        "name": "HR User",
        "department": "Human Resources",
    }


@pytest.fixture
def employee_token(employee_claims) -> str:
    return _make_token(employee_claims)


@pytest.fixture
def manager_token(manager_claims) -> str:
    return _make_token(manager_claims)


@pytest.fixture
def admin_token(admin_claims) -> str:
    return _make_token(admin_claims)


@pytest.fixture
def hr_token(hr_claims) -> str:
    return _make_token(hr_claims)


@pytest.fixture
def expired_token(employee_claims) -> str:
    return _make_token(employee_claims, expired=True)


@pytest.fixture
def wrong_secret_token(employee_claims) -> str:
    return _make_token(employee_claims, secret="WRONG_SECRET_KEY_1234567890123456")


# ============================================================================
# User Context Fixtures
# ============================================================================

@pytest.fixture
def employee_context(employee_claims) -> Dict[str, Any]:
    """User context as extracted by validate_and_extract_token."""
    return {
        "employeeId": employee_claims["employeeId"],
        "tenant": employee_claims["tenant"],
        "role": employee_claims["role"],
        "name": employee_claims["name"],
        "sub": employee_claims["sub"],
        "department": employee_claims.get("department", "Engineering"),
        "reportingManager": employee_claims.get("reportingManager", "MGR001"),
    }


@pytest.fixture
def manager_context(manager_claims) -> Dict[str, Any]:
    return {
        "employeeId": manager_claims["employeeId"],
        "tenant": manager_claims["tenant"],
        "role": manager_claims["role"],
        "name": manager_claims["name"],
        "sub": manager_claims["sub"],
        "department": manager_claims.get("department", "Engineering"),
    }


@pytest.fixture
def admin_context(admin_claims) -> Dict[str, Any]:
    return {
        "employeeId": admin_claims["employeeId"],
        "tenant": admin_claims["tenant"],
        "role": admin_claims["role"],
        "name": admin_claims["name"],
        "sub": admin_claims["sub"],
    }


# ============================================================================
# Catalog Fixture
# ============================================================================

@pytest.fixture
def loaded_catalog() -> Dict[str, Any]:
    """Load the real API catalog for testing."""
    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def all_endpoint_ids(loaded_catalog) -> list:
    """Extract every endpoint_id from the catalog."""
    ids = []
    for module_data in loaded_catalog.get("modules", {}).values():
        for ep in module_data.get("endpoints", []):
            eid = ep.get("endpoint_id")
            if eid:
                ids.append(eid)
    return ids


# ============================================================================
# Mock Settings Fixture
# ============================================================================

@pytest.fixture
def mock_settings():
    """Return a mock Settings object mirroring test .env."""
    settings = MagicMock()
    settings.JWT_SECRET = TEST_JWT_SECRET
    settings.JAVA_BACKEND_URL = TEST_JAVA_BACKEND_URL
    settings.HRMS_API_BASE_URL = TEST_JAVA_BACKEND_URL
    settings.CATALOG_PATH = CATALOG_PATH
    settings.LLM_MODEL = "gpt-4o-mini"
    settings.LLM_TEMPERATURE = 0.0
    settings.LLM_MAX_TOKENS = 4096
    settings.OPENAI_API_KEY = "sk-test-fake-key"
    settings.RAG_POLICIES_DIR = os.path.join(PROJECT_ROOT, "data", "policies")
    settings.ENABLE_CONFIRMATIONS = True
    settings.ENABLE_RAG = True
    settings.CHROMA_PERSIST_DIR = "./data/chroma"
    settings.CHROMA_COLLECTION = "xevyte_endpoints"
    settings.RAG_TOP_K = 12
    return settings


# ============================================================================
# Mock DB Session Fixture
# ============================================================================

@pytest.fixture
def mock_db_session():
    """Async mock for SQLAlchemy AsyncSession."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session


# ============================================================================
# Confirmation Token Factory
# ============================================================================

@pytest.fixture
def make_confirmation_token():
    """Factory fixture to generate confirmation tokens."""
    import base64
    from cryptography.fernet import Fernet

    secret = TEST_JWT_SECRET
    if len(secret) < 32:
        secret = secret.ljust(32, '0')
    else:
        secret = secret[:32]
    key = base64.urlsafe_b64encode(secret.encode('utf-8'))
    fernet = Fernet(key)

    def _make(action_data: dict, employee_id: str, expired: bool = False):
        payload = {
            "action": action_data,
            "employee_id": employee_id,
            "exp": int(time.time()) + (-3600 if expired else 3600),
        }
        payload_bytes = json.dumps(payload).encode('utf-8')
        return fernet.encrypt(payload_bytes).decode('utf-8')

    return _make
