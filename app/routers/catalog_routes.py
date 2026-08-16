from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from app.catalog.loader import get_catalog, load_catalog
from app.config import get_settings
from app.rag.ingest import ingest
from app.schemas import CatalogEndpointOut, CatalogRefreshResponse

router = APIRouter(prefix="/api/agent/catalog", tags=["catalog"])


class RefreshFromSourceRequest(BaseModel):
    java_source_dir: str | None = None  # defaults to JAVA_SOURCE_DIR from .env if omitted


@router.get("", response_model=list[CatalogEndpointOut])
async def list_endpoints(module: str | None = Query(default=None), q: str | None = Query(default=None)):
    catalog = get_catalog()
    eps = catalog.by_module(module) if module else catalog.endpoints
    if q:
        q_lower = q.lower()
        eps = [e for e in eps if q_lower in e.description.lower() or q_lower in e.path.lower()]
    return [
        CatalogEndpointOut(
            id=e.id, module=e.module, http_method=e.http_method, path=e.path, description=e.description,
            auth_required=e.auth_required, destructive_hint=e.destructive_hint,
            sensitive_module_hint=e.sensitive_module_hint,
        )
        for e in eps[:500]
    ]


@router.get("/modules")
async def list_modules():
    catalog = get_catalog()
    return {"modules": catalog.modules(), "count": len(catalog.modules())}


@router.post("/refresh", response_model=CatalogRefreshResponse)
async def refresh_catalog():
    """Reloads endpoint_catalog.json from disk and re-embeds it into Chroma.
    Run scripts/parse_java_endpoints.py first if the Java backend changed —
    this endpoint does NOT re-parse Java source, only re-syncs the RAG store
    from whatever's currently in app/catalog/endpoint_catalog.json. For the
    full re-parse-from-source in one call, see POST /refresh-from-source."""
    catalog = load_catalog()
    n_chunks = ingest(catalog)
    from app.rag.retriever import reload_bm25_index
    reload_bm25_index()
    try:
        from app.planes.knowledge.tool_registry import reload_tool_registry
        from app.planes.control.tool_discovery import reload_hybrid_index
        reload_tool_registry()
        reload_hybrid_index()
    except Exception:
        logger.exception("Failed to reload v2 tool registry / hybrid index after catalog refresh")
    return CatalogRefreshResponse(
        endpoints_discovered=len(catalog), modules=len(catalog.modules()), chunks_ingested=n_chunks
    )


@router.post("/refresh-from-source", response_model=CatalogRefreshResponse)
async def refresh_from_source(body: RefreshFromSourceRequest):
    """Full pipeline in one call: re-run the Java parser against the given
    (or configured JAVA_SOURCE_DIR) source tree, then re-embed the result.
    This is what the file watcher calls automatically when
    AUTO_WATCH_JAVA_SOURCE is on — call it manually, or from a CI/CD step
    right after deploying new Java code, when automatic filesystem
    watching isn't set up (e.g. the agent runs on a different host than
    the Java backend). Needs the Java source reachable on THIS machine's
    filesystem either way — a CI/CD call typically means checking out or
    mounting the Java repo somewhere the agent container can read first."""
    settings = get_settings()
    src_dir = body.java_source_dir or settings.JAVA_SOURCE_DIR
    if not src_dir:
        raise HTTPException(
            status_code=400,
            detail="No java_source_dir given and JAVA_SOURCE_DIR is not set in .env.",
        )
    from app.catalog.watcher import refresh_catalog_and_rag

    result = refresh_catalog_and_rag(src_dir)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=f"Parser failed:\n{result['message']}")
    return CatalogRefreshResponse(
        endpoints_discovered=result["endpoints_discovered"],
        modules=result["modules"],
        chunks_ingested=result["chunks_ingested"],
    )
