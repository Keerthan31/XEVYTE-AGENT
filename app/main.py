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
from app.routers import auth_routes, catalog_routes, chat, chat_v2

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


@app.on_event("startup")
async def on_startup():
    setup_langsmith()
    Base.metadata.create_all(bind=engine)  # no-op once sql/init_db.sql has been applied; safe either way
    try:
        catalog = load_catalog()
        logger.info(f"Loaded {len(catalog)} endpoints across {len(catalog.modules())} modules from catalog.")
    except FileNotFoundError as e:
        logger.warning(
            f"{e}\nStart the agent anyway, but /api/agent/chat will fail until the catalog exists. "
            f"Run scripts/parse_java_endpoints.py, then scripts/ingest_catalog.py."
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
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    ssl_kwargs = {}
    if settings.SSL_KEYFILE and settings.SSL_CERTFILE:
        ssl_kwargs = {"ssl_keyfile": settings.SSL_KEYFILE, "ssl_certfile": settings.SSL_CERTFILE}
    else:
        logger.warning("SSL_KEYFILE/SSL_CERTFILE not set — running plain HTTP. See certs/generate_self_signed.sh.")

    uvicorn.run("app.main:app", host=settings.SERVER_HOST, port=settings.SERVER_PORT, reload=False, **ssl_kwargs)
