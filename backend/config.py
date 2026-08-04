import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path, override=True)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")

XEVYTE_API_BASE = os.getenv("XEVYTE_API_BASE", "http://localhost:8080")

# ─── Resilience & Caching Configurations ──────────────────────────────────────
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "30"))
MAX_HTTP_RETRIES = int(os.getenv("MAX_HTTP_RETRIES", "3"))
HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "15.0"))

# ─── Observability & Tracing ──────────────────────────────────────────────────
# ─── Multi-Model Failover Array ───────────────────────────────────────────────
FALLBACK_MODELS = [
    OPENROUTER_MODEL,
    "deepseek/deepseek-chat",
    "qwen/qwen-2.5-72b-instruct",
    "meta-llama/llama-3.1-70b-instruct:free"
]


