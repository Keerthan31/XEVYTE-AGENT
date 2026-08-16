"""
Top-k hybrid retrieval over the endpoint catalog.

Combines:
  1. Chroma cosine semantic search (when the collection has vectors)
  2. BM25 lexical search over rich embedding_text() (always available)
  3. Optional module filter

This is what lets one agent cover 600+ endpoints without dumping them all
into the LLM context. Empty Chroma (fresh checkout / failed ingest) no
longer returns zero candidates — BM25 still finds tools.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

try:
    from rank_bm25 import BM25Okapi
except ImportError:  # pragma: no cover
    BM25Okapi = None  # type: ignore

from app.catalog.loader import EndpointSpec, get_catalog
from app.config import get_settings
from app.rag.ingest import get_or_create_collection

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9]*")
# Common stop/noise tokens that dominate BM25 when Chroma is empty
_QUERY_STOP = {
    "my", "me", "i", "the", "a", "an", "to", "for", "of", "and", "or", "please", "can", "you",
    "check", "show", "get", "view", "see", "want", "need", "tell", "give", "what", "how",
}
# Lightweight query expansions when semantic search is unavailable
_SYNONYMS: dict[str, list[str]] = {
    "payslip": ["payslips", "salary", "slip", "pay", "payroll"],
    "payslips": ["payslip", "salary", "slip", "payroll"],
    "leave": ["leaves", "pto", "vacation", "absence"],
    "balance": ["balances", "remaining", "quota"],
    "ticket": ["tickets", "helpdesk", "support", "issue"],
    "attendance": ["punch", "checkin", "checkout", "daily"],
    "claim": ["claims", "reimbursement", "expense"],
    "asset": ["assets", "allocation", "inventory"],
}

_bm25_corpus: list[EndpointSpec] | None = None
_bm25_index: Any = None
_bm25_tokens: list[list[str]] | None = None


@dataclass
class RetrievedEndpoint:
    endpoint: EndpointSpec
    score: float  # higher is more relevant
    semantic_score: float = 0.0
    bm25_score: float = 0.0


def _stem_variants(token: str) -> list[str]:
    """Simple plural/singular variants so 'payslip' matches 'payslips'."""
    out = [token]
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        out.append(token[:-1])
    elif len(token) > 3 and not token.endswith("s"):
        out.append(token + "s")
    return out


def _tokenize(text: str) -> list[str]:
    raw = [t.lower() for t in _TOKEN_RE.findall(text or "")]
    expanded: list[str] = []
    for t in raw:
        expanded.extend(_stem_variants(t))
    return expanded


def _expand_query(query: str) -> str:
    """Append synonym tokens for HR domain terms (helps empty-Chroma BM25)."""
    toks = [t.lower() for t in _TOKEN_RE.findall(query or "")]
    extras: list[str] = []
    for t in toks:
        for syn in _SYNONYMS.get(t, []):
            extras.append(syn)
    if not extras:
        return query
    return query + " " + " ".join(extras)


def _content_term_boost(query: str, endpoint: EndpointSpec) -> float:
    """Boost endpoints whose path/id contain rare content terms from the query.

    Fixes runtime failure where 'check my payslip' ranked tickets/roles above
    payslip because BM25 overweighted 'check'/'my' while 'payslip'≠'payslips'.
    """
    q_raw = [t.lower() for t in _TOKEN_RE.findall(query or "")]
    content = [t for t in q_raw if t not in _QUERY_STOP and len(t) > 2]
    if not content:
        return 0.0
    hay = f"{endpoint.id} {endpoint.path} {endpoint.module} {endpoint.method_name} {endpoint.description}".lower()
    boost = 0.0
    for term in content:
        variants = set(_stem_variants(term)) | set(_SYNONYMS.get(term, []))
        if any(v in hay for v in variants):
            boost += 0.35
    return min(boost, 1.0)


def _ensure_bm25() -> tuple[list[EndpointSpec], Any]:
    global _bm25_corpus, _bm25_index, _bm25_tokens
    catalog = get_catalog()
    if _bm25_corpus is None or len(_bm25_corpus) != len(catalog):
        _bm25_corpus = list(catalog.endpoints)
        _bm25_tokens = [_tokenize(ep.embedding_text()) for ep in _bm25_corpus]
        if BM25Okapi is not None and _bm25_tokens:
            _bm25_index = BM25Okapi(_bm25_tokens)
        else:
            _bm25_index = None
            if BM25Okapi is None:
                logger.warning("rank_bm25 not installed — using simple token overlap scoring")
    return _bm25_corpus, _bm25_index  # type: ignore[return-value]


def reload_bm25_index() -> None:
    global _bm25_corpus, _bm25_index, _bm25_tokens
    _bm25_corpus = None
    _bm25_index = None
    _bm25_tokens = None
    _ensure_bm25()


def _collection_count() -> int:
    try:
        return int(get_or_create_collection().count())
    except Exception as e:
        logger.warning("Chroma collection unavailable: %s", e)
        return 0


def _semantic_scores(query: str, top_k: int, module_filter: str | None) -> dict[str, float]:
    if _collection_count() <= 0:
        return {}
    try:
        collection = get_or_create_collection()
        where = {"module": module_filter} if module_filter else None
        result = collection.query(
            query_texts=[query],
            n_results=min(top_k * 3, 60),
            where=where,
        )
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        return {tid: max(0.0, 1.0 - float(dist)) for tid, dist in zip(ids, distances)}
    except Exception as e:
        logger.warning("Semantic retrieval failed, falling back to BM25: %s", e)
        return {}


def _simple_overlap_scores(query: str, module_filter: str | None) -> dict[str, float]:
    """Fallback when rank_bm25 is unavailable."""
    q = set(_tokenize(query))
    if not q:
        return {}
    corpus, _ = _ensure_bm25()
    out: dict[str, float] = {}
    for ep in corpus:
        if module_filter and ep.module != module_filter:
            continue
        tokens = set(_tokenize(ep.embedding_text()))
        if not tokens:
            continue
        overlap = len(q & tokens) / max(len(q), 1)
        if overlap > 0:
            out[ep.id] = overlap
    return out


def _bm25_scores(query: str, module_filter: str | None) -> dict[str, float]:
    corpus, index = _ensure_bm25()
    if index is None:
        return _simple_overlap_scores(query, module_filter)
    raw = index.get_scores(_tokenize(query))
    max_score = max(raw) if len(raw) and max(raw) > 0 else 1.0
    out: dict[str, float] = {}
    for i, ep in enumerate(corpus):
        if module_filter and ep.module != module_filter:
            continue
        out[ep.id] = float(raw[i]) / max_score
    return out


def retrieve(
    query: str,
    top_k: int | None = None,
    module_filter: str | None = None,
    *,
    weights: tuple[float, float] = (0.40, 0.60),  # bm25, semantic
    min_score: float = 0.04,
) -> list[RetrievedEndpoint]:
    settings = get_settings()
    top_k = top_k or settings.RAG_TOP_K
    catalog = get_catalog()

    expanded = _expand_query(query)
    w_bm25, w_sem = weights
    bm25 = _bm25_scores(expanded, module_filter)
    semantic = _semantic_scores(query, top_k, module_filter)

    # If Chroma is empty, lean entirely on BM25 so the agent still works.
    if not semantic:
        w_bm25, w_sem = 1.0, 0.0

    all_ids = set(bm25) | set(semantic)
    scored: list[RetrievedEndpoint] = []
    for eid in all_ids:
        ep = catalog.get(eid)
        if ep is None:
            continue
        b = bm25.get(eid, 0.0)
        s = semantic.get(eid, 0.0)
        boost = _content_term_boost(query, ep) if not semantic else 0.0
        final = w_bm25 * b + w_sem * s + boost
        if final < min_score:
            continue
        scored.append(
            RetrievedEndpoint(endpoint=ep, score=final, semantic_score=s, bm25_score=b)
        )

    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[:top_k]


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
