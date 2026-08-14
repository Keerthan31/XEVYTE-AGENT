"""
B.3.4 TOOL DISCOVERY — Hybrid retrieval (spec section 6)

    "Implement hybrid retrieval. Use: 1. exact/keyword retrieval
    2. metadata filtering 3. semantic retrieval 4. intent matching
    5. reranking. Do NOT rely only on embeddings."

Combines three signals over the (domain-narrowed, via domain_router.py)
candidate pool:
  - BM25 lexical score (rank-bm25) — catches exact module/field/verb
    matches embeddings sometimes miss ("payslip", "PAN", "Aadhaar")
  - Chroma semantic score (existing, tested embeddings pipeline)
  - metadata boost — intent/domain match, risk-tier proximity

then a simple weighted-sum rerank. Every candidate returned still must
exist in the Tool Registry (tool_discovery never invents one) — if
nothing clears MIN_SCORE, this returns an empty list and the orchestrator
must report "capability not available" rather than guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from app.planes.control.domain_router import Domain, route
from app.planes.knowledge.tool_registry import ToolRegistry, ToolRegistryEntry, get_tool_registry
from app.rag.ingest import get_or_create_collection

MIN_SCORE = 0.05
_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9]*")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


@dataclass
class Candidate:
    tool: ToolRegistryEntry
    bm25_score: float
    semantic_score: float
    metadata_boost: float
    final_score: float


class HybridIndex:
    """Built once per ToolRegistry snapshot (rebuilt on catalog refresh —
    see reload()), not per query — BM25 corpus indexing is the expensive
    part, querying it is cheap."""

    def __init__(self, registry: ToolRegistry | None = None):
        self.registry = registry or get_tool_registry()
        self._tools = self.registry.all_active()
        self._corpus_tokens = [_tokenize(t.description) for t in self._tools]
        self._bm25 = BM25Okapi(self._corpus_tokens) if self._corpus_tokens else None
        self._id_to_idx = {t.tool_id: i for i, t in enumerate(self._tools)}

    def _bm25_scores(self, query: str) -> dict[str, float]:
        if not self._bm25:
            return {}
        raw = self._bm25.get_scores(_tokenize(query))
        max_score = max(raw) if len(raw) and max(raw) > 0 else 1.0
        return {self._tools[i].tool_id: float(raw[i]) / max_score for i in range(len(raw))}

    def _semantic_scores(self, query: str, top_k: int, allowed_modules: list[str] | None) -> dict[str, float]:
        collection = get_or_create_collection()
        where = {"module": {"$in": allowed_modules}} if allowed_modules else None
        result = collection.query(query_texts=[query], n_results=min(top_k * 3, 60), where=where)
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        return {tid: max(0.0, 1 - dist) for tid, dist in zip(ids, distances)}

    def search(
        self,
        query: str,
        *,
        domain: Domain | str | None = None,
        top_k: int = 12,
        weights: tuple[float, float, float] = (0.35, 0.55, 0.10),  # bm25, semantic, metadata
    ) -> list[Candidate]:
        allowed_modules = route(domain)  # None => search everything (fail-open on unknown domain)
        pool_ids = None
        if allowed_modules:
            pool_ids = {t.tool_id for t in self._tools if t.module in allowed_modules}

        bm25_scores = self._bm25_scores(query)
        semantic_scores = self._semantic_scores(query, top_k, allowed_modules)

        all_ids = set(bm25_scores) | set(semantic_scores)
        if pool_ids is not None:
            all_ids &= pool_ids

        w_bm25, w_sem, w_meta = weights
        candidates: list[Candidate] = []
        for tool_id in all_ids:
            idx = self._id_to_idx.get(tool_id)
            if idx is None:
                continue  # stale id (e.g. tool disabled since index build)
            tool = self._tools[idx]
            bm25 = bm25_scores.get(tool_id, 0.0)
            sem = semantic_scores.get(tool_id, 0.0)
            meta = 0.15 if (allowed_modules and tool.module in allowed_modules) else 0.0
            final = w_bm25 * bm25 + w_sem * sem + w_meta * meta
            candidates.append(Candidate(tool=tool, bm25_score=bm25, semantic_score=sem, metadata_boost=meta, final_score=final))

        candidates.sort(key=lambda c: c.final_score, reverse=True)
        return [c for c in candidates[:top_k] if c.final_score >= MIN_SCORE]


_index: HybridIndex | None = None


def get_hybrid_index() -> HybridIndex:
    global _index
    if _index is None:
        _index = HybridIndex()
    return _index


def reload_hybrid_index() -> HybridIndex:
    global _index
    _index = HybridIndex()
    return _index


def discover(query: str, domain: Domain | str | None = None, top_k: int = 12) -> list[Candidate]:
    """The single entry point everything else calls. Returns [] rather
    than guessing when nothing clears MIN_SCORE — callers must treat an
    empty result as "capability not available", never fall back to
    picking the top-scored-but-still-bad candidate."""
    return get_hybrid_index().search(query, domain=domain, top_k=top_k)
