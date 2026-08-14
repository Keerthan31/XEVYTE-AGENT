"""
A tiny ChromaDB-compatible embedding function backed by LiteLLM, so the
embedding provider is swappable purely through .env (OpenAI by default;
point EMBEDDING_MODEL at any LiteLLM-supported model — Cohere, Voyage,
a local Ollama endpoint, etc. — to switch).
"""
from __future__ import annotations

import litellm
from chromadb import Documents, EmbeddingFunction, Embeddings
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings


class LiteLLMEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model: str | None = None, api_key: str | None = None):
        settings = get_settings()
        self.model = model or settings.EMBEDDING_MODEL
        self.api_key = api_key or settings.EMBEDDING_PROVIDER_API_KEY or settings.OPENAI_API_KEY

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=1, max=20))
    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        resp = litellm.embedding(model=self.model, input=texts, api_key=self.api_key)
        return [d["embedding"] for d in resp.data]

    def __call__(self, input: Documents) -> Embeddings:  # noqa: A002 - Chroma's own interface names it `input`
        texts = list(input)
        if not texts:
            return []
        # LiteLLM/OpenAI embedding endpoints accept batches; chunk defensively
        # for very large ingests so one oversized request can't fail the lot.
        out: list[list[float]] = []
        batch_size = 96
        for i in range(0, len(texts), batch_size):
            out.extend(self._embed_batch(texts[i : i + batch_size]))
        return out
