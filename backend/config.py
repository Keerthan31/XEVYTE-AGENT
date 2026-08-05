import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path, override=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

XEVYTE_API_BASE = os.getenv("XEVYTE_API_BASE", "http://localhost:8080")

# ─── Resilience & Caching Configurations ──────────────────────────────────────
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "30"))
MAX_HTTP_RETRIES = int(os.getenv("MAX_HTTP_RETRIES", "3"))
HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "15.0"))

# ─── Observability & Tracing (LangSmith) ──────────────────────────────────────
LANGCHAIN_TRACING_V2 = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
LANGCHAIN_API_KEY = os.getenv("LANGCHAIN_API_KEY", "")
LANGCHAIN_PROJECT = os.getenv("LANGCHAIN_PROJECT", "Xevyte-HRMS-Agent")

# ─── Multi-Model Failover Array ───────────────────────────────────────────────
FALLBACK_MODELS = [
    OPENAI_MODEL,
    "gpt-3.5-turbo"
]



