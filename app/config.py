"""
Central configuration. Everything is loaded from environment variables /
.env via pydantic-settings so nothing sensitive is hardcoded in source.

load_dotenv() below is deliberate and not redundant with pydantic-settings'
own env_file support: pydantic-settings reads .env into the Settings
object only, but several requested libraries (deepeval's judge model,
litellm's provider auto-detection, the raw openai SDK's env fallback)
read os.environ directly and never see our Settings object at all. Calling
load_dotenv() first makes .env values visible both ways.
"""
from functools import lru_cache
from typing import Optional

import os
from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

# Prevent empty environment variables (like OPENAI_BASE_URL="") from polluting
# SDKs that inspect os.environ directly (such as the OpenAI/httpx client).
for _k, _v in list(os.environ.items()):
    if isinstance(_v, str) and not _v.strip():
        os.environ.pop(_k, None)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator(
        "OPENAI_BASE_URL",
        "EMBEDDING_PROVIDER_API_KEY",
        "LANGCHAIN_API_KEY",
        "JAVA_SOURCE_DIR",
        "SSL_KEYFILE",
        "SSL_CERTFILE",
        mode="before",
    )
    @classmethod
    def _empty_str_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v

    # ---- Xevyte Connect HRMS backend (the real Java API this agent calls) ----
    HRMS_API_BASE_URL: str = Field(
        default="http://localhost:8082",
        description="Base URL of the employee-login-backend2 Spring Boot service.",
    )
    HRMS_API_TIMEOUT_SECONDS: float = 30.0

    # ---- Scaloz IAM SSO (the SAME login Xevyte Connect's own frontend uses) ----
    # The agent never mints or verifies JWTs itself — it never touches the
    # backend's JWT_SECRET. It only redirects the user through the same SSO
    # flow the React frontend uses (SSOHandler.js) and reuses the resulting
    # token as a Bearer token, exactly like the frontend does in api.js.
    SCALOZ_IAM_URL: str = Field(default="https://workspacetest.scaloz.com")
    AGENT_PUBLIC_URL: str = Field(
        default="https://localhost:8443",
        description="Public URL of THIS agent service, used as the SSO redirect_to target.",
    )

    # ---- LLM provider ----
    # Default: OpenAI directly (langchain-openai's ChatOpenAI + instructor).
    # To swap providers without touching code, point OPENAI_BASE_URL at a
    # LiteLLM proxy (https://docs.litellm.ai/docs/proxy/quick_start) or any
    # OpenAI-compatible endpoint (OpenRouter, Azure OpenAI, vLLM, etc.) and
    # set OPENAI_API_KEY accordingly.
    OPENAI_API_KEY: str = Field(default="")
    OPENAI_BASE_URL: Optional[str] = Field(default=None)
    CHAT_MODEL: str = Field(default="gpt-4o-mini")
    PLANNER_MODEL: str = Field(default="gpt-4o-mini")

    # Embeddings — routed through LiteLLM so the provider is swappable
    # independently of the chat model (e.g. keep chat on OpenAI but use a
    # cheaper/local embedding model).
    EMBEDDING_MODEL: str = Field(default="text-embedding-3-small")
    EMBEDDING_PROVIDER_API_KEY: Optional[str] = Field(default=None, description="Defaults to OPENAI_API_KEY if unset")

    # ---- LangSmith tracing (optional) ----
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_API_KEY: Optional[str] = None
    LANGCHAIN_PROJECT: str = "xevyte-agent"

    # ---- Postgres ----
    DATABASE_URL: str = Field(
        default="postgresql+psycopg2://xevyte_agent:xevyte_agent@localhost:5432/xevyte_agent",
    )

    # ---- Chroma (RAG store) ----
    CHROMA_PERSIST_DIR: str = "./data/chroma"
    CHROMA_COLLECTION: str = "xevyte_endpoints"
    RAG_TOP_K: int = 12

    # ---- Catalog ----
    ENDPOINT_CATALOG_PATH: str = "app/catalog/endpoint_catalog.json"
    OPENAPI_CATALOG_PATH: str = "app/catalog/openapi_catalog.json"

    # ---- Live catalog auto-refresh ----
    # If set, the agent watches this directory (the Java controller/dto/
    # payload/entity source — same --src you'd pass to
    # scripts/parse_java_endpoints.py) for .java changes and automatically
    # re-parses + re-embeds the catalog a few seconds after things go quiet.
    # Only works when the agent has filesystem access to that source (same
    # host, or a mounted volume in Docker/k8s) — see JAVA_SOURCE_WATCH_DEBOUNCE_SECONDS
    # and app/catalog/watcher.py. Leave unset to disable (default) and
    # trigger refreshes manually or from CI/CD instead via
    # POST /api/agent/catalog/refresh-from-source.
    JAVA_SOURCE_DIR: Optional[str] = None
    AUTO_WATCH_JAVA_SOURCE: bool = False
    JAVA_SOURCE_WATCH_DEBOUNCE_SECONDS: float = 4.0

    # ---- Session / crypto ----
    SESSION_SECRET_KEY: str = Field(
        default="",
        description="32+ byte random secret used ONLY to encrypt agent session cookies "
                    "at rest in Postgres. Unrelated to the HRMS backend's JWT_SECRET — "
                    "generate your own with: python -c \"import secrets;print(secrets.token_urlsafe(32))\"",
    )
    SESSION_COOKIE_NAME: str = "xevyte_agent_session"
    SESSION_TTL_HOURS: int = 12

    # ---- Guardrails ----
    REQUIRE_CONFIRMATION_ABOVE_RISK: str = Field(
        default="HIGH",
        description="LOW | MEDIUM | HIGH | CRITICAL — tiers at or above this require explicit user confirmation before execution. Default HIGH so ordinary leave/ticket writes are not blocked by 'should I go ahead?'.",
    )

    # ---- HTTPS (uvicorn) ----
    SSL_KEYFILE: Optional[str] = None
    SSL_CERTFILE: Optional[str] = None
    SERVER_HOST: str = "0.0.0.0"
    SERVER_PORT: int = 8443

    # ---- CORS ----
    CORS_ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:3001,http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()
