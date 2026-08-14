"""
Embeds every endpoint in the catalog into a persistent Chroma collection so
the agent can semantically retrieve the handful of relevant endpoints (out
of 600+) for a given natural-language request, instead of ever having to
list all 600+ as LLM tools/context at once.

Re-run after regenerating the catalog:
    python scripts/ingest_catalog.py
"""
from __future__ import annotations

import chromadb

from app.catalog.loader import Catalog, get_catalog
from app.config import get_settings
from app.rag.embeddings import LiteLLMEmbeddingFunction


def get_chroma_client() -> chromadb.ClientAPI:
    settings = get_settings()
    return chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)


def get_or_create_collection(client: chromadb.ClientAPI | None = None):
    settings = get_settings()
    client = client or get_chroma_client()
    return client.get_or_create_collection(
        name=settings.CHROMA_COLLECTION,
        embedding_function=LiteLLMEmbeddingFunction(),
        metadata={"hnsw:space": "cosine"},
    )


def ingest(catalog: Catalog | None = None) -> int:
    """(Re)builds the collection from scratch so stale/removed endpoints
    never linger. Returns the number of chunks ingested."""
    settings = get_settings()
    catalog = catalog or get_catalog()
    client = get_chroma_client()

    # Drop and recreate so deleted/renamed endpoints don't leave orphaned
    # vectors behind — the catalog JSON is the single source of truth.
    try:
        client.delete_collection(settings.CHROMA_COLLECTION)
    except Exception:
        pass
    collection = client.get_or_create_collection(
        name=settings.CHROMA_COLLECTION,
        embedding_function=LiteLLMEmbeddingFunction(),
        metadata={"hnsw:space": "cosine"},
    )

    ids, docs, metadatas = [], [], []
    for ep in catalog.endpoints:
        ids.append(ep.id)
        docs.append(ep.embedding_text())
        metadatas.append(
            {
                "module": ep.module,
                "http_method": ep.http_method,
                "path": ep.path,
                "destructive_hint": ep.destructive_hint,
                "bulk_hint": ep.bulk_hint,
                "sensitive_module_hint": ep.sensitive_module_hint,
                "auth_required": ep.auth_required,
            }
        )

    batch_size = 200
    for i in range(0, len(ids), batch_size):
        collection.add(
            ids=ids[i : i + batch_size],
            documents=docs[i : i + batch_size],
            metadatas=metadatas[i : i + batch_size],
        )

    return len(ids)


if __name__ == "__main__":
    n = ingest()
    print(f"Ingested {n} endpoint embeddings into Chroma.")
