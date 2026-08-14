#!/usr/bin/env python3
"""
Standalone catalog -> Chroma ingestion.

    python scripts/ingest_catalog.py

Run this once after scripts/parse_java_endpoints.py, and again any time
the catalog changes. (POST /api/agent/catalog/refresh does the same thing
over HTTP once the server is already running.)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.catalog.loader import load_catalog  # noqa: E402
from app.rag.ingest import ingest  # noqa: E402

if __name__ == "__main__":
    catalog = load_catalog()
    print(f"Loaded {len(catalog)} endpoints across {len(catalog.modules())} modules.")
    n = ingest(catalog)
    print(f"Ingested {n} endpoint embeddings into Chroma at the configured CHROMA_PERSIST_DIR.")
