"""
Retrieval recall@k eval — deterministic, no LLM-as-judge needed (just an
embedding call). Verifies the RAG retriever actually surfaces the right
endpoint, out of 633, for realistic natural-language HRMS requests spanning
many modules. This is the eval that matters most in practice: the planner
can only pick correctly among whatever retrieval hands it.

Run:
    python -m pytest evals/test_retrieval.py -v

Needs: app/catalog/endpoint_catalog.json to exist (run
scripts/parse_java_endpoints.py first) and OPENAI_API_KEY / EMBEDDING_MODEL
configured in .env (or point EMBEDDING_MODEL at any other LiteLLM-supported
embedding model — see app/rag/embeddings.py).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.catalog.loader import load_catalog  # noqa: E402
from app.rag.ingest import ingest  # noqa: E402
from app.rag.retriever import retrieve  # noqa: E402

GOLDEN_PATH = Path(__file__).parent / "golden_queries.json"


@pytest.fixture(scope="module", autouse=True)
def _ensure_ingested():
    """Ingest the real catalog into Chroma once for this test module. If
    you've already run scripts/ingest_catalog.py this just re-embeds
    (idempotent — ingest() always rebuilds the collection from scratch)."""
    catalog = load_catalog()
    ingest(catalog)


def _golden_cases():
    return json.loads(GOLDEN_PATH.read_text())


@pytest.mark.parametrize("case", _golden_cases(), ids=lambda c: c["query"][:40])
def test_expected_endpoint_in_top_k(case):
    results = retrieve(case["query"], top_k=12)
    retrieved_ids = [r.endpoint.id for r in results]
    assert case["expected_endpoint_id"] in retrieved_ids, (
        f"Expected '{case['expected_endpoint_id']}' in top-12 for query "
        f"{case['query']!r}, got: {retrieved_ids}"
    )


def test_recall_at_k_overall():
    """Aggregate recall@12 across the whole golden set — a coarse signal
    for whether RAG_TOP_K is generous enough / embedding model is doing
    its job. Fails the module if recall drops below 80%, which is a sign
    something upstream broke (catalog description quality, embedding
    model swap, RAG_TOP_K set too low) rather than one query being hard."""
    cases = _golden_cases()
    hits = 0
    for case in cases:
        retrieved_ids = [r.endpoint.id for r in retrieve(case["query"], top_k=12)]
        if case["expected_endpoint_id"] in retrieved_ids:
            hits += 1
    recall = hits / len(cases)
    print(f"\nRecall@12 over {len(cases)} golden queries: {recall:.0%}")
    assert recall >= 0.8, f"Recall@12 dropped to {recall:.0%} — investigate before shipping"
