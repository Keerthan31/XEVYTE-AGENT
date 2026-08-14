"""
Top-k semantic retrieval over the ingested endpoint catalog. This is what
lets one agent cover 600+ endpoints: for any given user message, we never
show the LLM more than RAG_TOP_K candidate endpoints, selected by meaning
rather than keyword match.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.catalog.loader import EndpointSpec, get_catalog
from app.config import get_settings
from app.rag.ingest import get_or_create_collection


@dataclass
class RetrievedEndpoint:
    endpoint: EndpointSpec
    score: float  # 1 - cosine distance; higher is more relevant


def retrieve(query: str, top_k: int | None = None, module_filter: str | None = None) -> list[RetrievedEndpoint]:
    settings = get_settings()
    top_k = top_k or settings.RAG_TOP_K
    collection = get_or_create_collection()
    catalog = get_catalog()

    where = {"module": module_filter} if module_filter else None
    result = collection.query(query_texts=[query], n_results=top_k, where=where)

    out: list[RetrievedEndpoint] = []
    ids = result.get("ids", [[]])[0]
    distances = result.get("distances", [[]])[0]
    for endpoint_id, distance in zip(ids, distances):
        ep = catalog.get(endpoint_id)
        if ep is None:
            continue  # stale vector from a since-removed endpoint; ignore
        out.append(RetrievedEndpoint(endpoint=ep, score=1 - distance))
    out.sort(key=lambda r: r.score, reverse=True)
    return out


def retrieve_many(queries: list[str], top_k_each: int = 6) -> list[RetrievedEndpoint]:
    """Used when a single user turn plausibly needs several distinct
    endpoints (e.g. 'show my leave balance and my last payslip'). Dedupes
    by endpoint id, keeping the highest score seen."""
    best: dict[str, RetrievedEndpoint] = {}
    for q in queries:
        for r in retrieve(q, top_k=top_k_each):
            if r.endpoint.id not in best or r.score > best[r.endpoint.id].score:
                best[r.endpoint.id] = r
    return sorted(best.values(), key=lambda r: r.score, reverse=True)
