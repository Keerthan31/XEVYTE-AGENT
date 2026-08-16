"""
FastAPI entrypoint.

Run directly for local HTTPS dev (self-signed cert — see certs/):
    python -m app.main

Or via uvicorn (what the Dockerfile uses):
    uvicorn app.main:app --host 0.0.0.0 --port 8443 \
        --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem

In production, terminate TLS at a reverse proxy (nginx/Caddy/ALB) with a
real CA-issued cert and run uvicorn plain HTTP behind it instead — either
is a legitimate way to satisfy "HTTPS"; self-signed uvicorn is for local
dev only, since browsers/clients won't trust it otherwise.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.llm import setup_langsmith
from app.catalog.loader import load_catalog
from app.config import get_settings
from app.database import Base, engine
from app.routers import auth_routes, catalog_routes, chat, chat_v2, sessions

from app.startup_checks import check_readiness

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("xevyte_agent")

settings = get_settings()

app = FastAPI(
    title="Xevyte Connect HRMS Agent",
    description=(
        "Single conversational agent over the entire Xevyte Connect HRMS API surface — "
        "633 auto-discovered endpoints across 84 modules, retrieved via RAG rather than "
        "hardcoded per-endpoint, executed with the caller's own Scaloz IAM session."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ALLOWED_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(chat.router)
app.include_router(chat_v2.router)
app.include_router(catalog_routes.router)
app.include_router(sessions.router)


@app.on_event("startup")
async def on_startup():
    setup_langsmith()
    try:
        Base.metadata.create_all(bind=engine)  # no-op once sql/init_db.sql has been applied; safe either way
    except Exception as e:
        err = str(e).lower()
        if "role" in err and "does not exist" in err or "connection refused" in err or "could not connect" in err:
            logger.error(
                "Cannot connect to Postgres at DATABASE_URL. The agent needs the xevyte_agent database.\n"
                "  Quick fix (recommended): from agents-main run:  docker compose up -d postgres\n"
                "  Then retry:  python -m app.main\n"
                "  Or point DATABASE_URL in .env at your own Postgres instance."
            )
        raise
    try:
        catalog = load_catalog()
        logger.info(f"Loaded {len(catalog)} endpoints across {len(catalog.modules())} modules from catalog.")
    except FileNotFoundError as e:
        logger.warning(
            f"{e}\nStart the agent anyway, but /api/agent/chat will fail until the catalog exists. "
            f"Run scripts/parse_java_endpoints.py, then scripts/ingest_catalog.py."
        )
        catalog = None

    # Ensure RAG store is populated — empty Chroma is the #1 cause of "unable to find tool"
    if catalog is not None:
        try:
            from app.rag.ingest import get_or_create_collection, ingest
            from app.rag.retriever import reload_bm25_index
            count = 0
            try:
                count = get_or_create_collection().count()
            except Exception:
                count = 0
            if count < len(catalog):
                if not settings.OPENAI_API_KEY and not settings.EMBEDDING_PROVIDER_API_KEY:
                    logger.warning(
                        "Chroma has %s vectors but catalog has %s endpoints, and no embedding API key "
                        "is set — BM25 keyword search will still work; run scripts/ingest_catalog.py "
                        "after setting OPENAI_API_KEY for full semantic retrieval.",
                        count, len(catalog),
                    )
                else:
                    logger.info("Chroma collection incomplete (%s/%s) — re-ingesting catalog embeddings...", count, len(catalog))
                    n = ingest(catalog)
                    logger.info("Ingested %s endpoint embeddings into Chroma.", n)
            reload_bm25_index()
        except Exception:
            logger.exception("Startup RAG warm-up failed — BM25 fallback may still work")

    report = check_readiness(len(catalog) if catalog is not None else 0)
    app.state.readiness = report
    if report.issues:
        for issue in report.issues:
            logger.error("STARTUP ISSUE: %s", issue)
    else:
        logger.info(
            "Agent ready: %s endpoints, %s Chroma vectors, LLM configured.",
            report.catalog_endpoint_count,
            report.chroma_vector_count,
        )

    if settings.AUTO_WATCH_JAVA_SOURCE:
        if not settings.JAVA_SOURCE_DIR:
            logger.warning("AUTO_WATCH_JAVA_SOURCE=true but JAVA_SOURCE_DIR is not set — skipping live watch.")
        else:
            from app.catalog.watcher import start_watcher
            app.state.java_watcher = start_watcher(
                settings.JAVA_SOURCE_DIR,
                str(Path(settings.ENDPOINT_CATALOG_PATH).parent),
                settings.JAVA_SOURCE_WATCH_DEBOUNCE_SECONDS,
            )


@app.on_event("shutdown")
async def on_shutdown():
    watcher = getattr(app.state, "java_watcher", None)
    if watcher is not None:
        watcher.stop()
        watcher.join(timeout=5)


@app.get("/health")
async def health():
    report = getattr(app.state, "readiness", None)
    if report is None:
        report = check_readiness()
    body = {"status": "ok" if report.ready else "degraded", **report.to_dict()}
    return body


# Serve the React UI from frontend/dist when present (npm run build in frontend/).
_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="frontend-assets")

    @app.get("/")
    async def spa_index():
        return FileResponse(_FRONTEND_DIST / "index.html")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        # Keep API/docs routes exclusive; only fall through for UI paths.
        if full_path.startswith("api/") or full_path in {"health", "docs", "openapi.json", "redoc"}:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = _FRONTEND_DIST / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_DIST / "index.html")
else:
    @app.get("/")
    async def root_no_ui():
        return {
            "service": "xevyte-agent",
            "health": "/health",
            "hint": "UI not built. From frontend/: npm install && npm run build  (or npm run dev on :3000)",
        }


if __name__ == "__main__":
    import uvicorn

    ssl_kwargs = {}
    if settings.SSL_KEYFILE and settings.SSL_CERTFILE:
        ssl_kwargs = {"ssl_keyfile": settings.SSL_KEYFILE, "ssl_certfile": settings.SSL_CERTFILE}
    else:
        logger.warning("SSL_KEYFILE/SSL_CERTFILE not set — running plain HTTP. See certs/generate_self_signed.sh.")

    uvicorn.run("app.main:app", host=settings.SERVER_HOST, port=settings.SERVER_PORT, reload=False, **ssl_kwargs)
