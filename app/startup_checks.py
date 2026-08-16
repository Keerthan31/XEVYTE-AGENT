"""Startup readiness checks — surfaced via /health and chat early-exit."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.config import get_settings


@dataclass
class ReadinessReport:
    llm_configured: bool
    chroma_vector_count: int
    catalog_endpoint_count: int
    issues: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.llm_configured and not any("catalog" in i.lower() for i in self.issues)

    def to_dict(self) -> dict:
        return {
            "ready": self.ready,
            "llm_configured": self.llm_configured,
            "chroma_vector_count": self.chroma_vector_count,
            "catalog_endpoint_count": self.catalog_endpoint_count,
            "semantic_search": self.chroma_vector_count > 0,
            "issues": self.issues,
        }


def check_readiness(catalog_count: int | None = None) -> ReadinessReport:
    settings = get_settings()
    issues: list[str] = []

    llm_configured = bool((settings.OPENAI_API_KEY or "").strip())
    if not llm_configured:
        issues.append(
            "OPENAI_API_KEY is not set — copy .env.example to .env and add your key, then restart the agent."
        )

    if not (settings.SESSION_SECRET_KEY or "").strip():
        issues.append(
            "SESSION_SECRET_KEY is empty — set a random secret in .env (python -c \"import secrets;print(secrets.token_urlsafe(32))\") or sessions may reset on restart."
        )

    chroma_count = 0
    try:
        from app.rag.ingest import get_or_create_collection
        chroma_count = int(get_or_create_collection().count())
    except Exception as e:
        issues.append(f"Chroma unavailable: {e}")

    ep_count = catalog_count or 0
    if ep_count == 0:
        issues.append("Endpoint catalog not loaded — run scripts/parse_java_endpoints.py")
    elif chroma_count < ep_count and llm_configured:
        issues.append(
            f"Chroma has {chroma_count}/{ep_count} vectors — run: python scripts/ingest_catalog.py"
        )
    elif chroma_count < ep_count:
        issues.append(
            f"Chroma empty ({chroma_count} vectors) — BM25 keyword search active; set OPENAI_API_KEY and run ingest_catalog.py for semantic search."
        )

    return ReadinessReport(
        llm_configured=llm_configured,
        chroma_vector_count=chroma_count,
        catalog_endpoint_count=ep_count,
        issues=issues,
    )
