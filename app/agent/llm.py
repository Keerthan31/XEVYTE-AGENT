"""
Central place every LLM call goes through.

Two distinct clients are used deliberately for two distinct jobs:
  - `instructor` + raw OpenAI client -> the PLANNING step (pick one endpoint
    out of the RAG candidates, extract path/query/body args as a strictly
    validated Pydantic object). Structured extraction is instructor's whole
    job; asking a chat model to "return JSON" and hoping it parses is not
    reliable enough when the output drives a real write/delete call.
  - `langchain_openai.ChatOpenAI` (via LangGraph nodes) -> the RESPONSE
    step (turn an API result into a natural-language reply). Free-form
    text generation is what LangChain's chat model wrapper is built for,
    and keeps this node trivially swappable/composable within the graph.

Both point at the same OPENAI_BASE_URL/OPENAI_API_KEY, so swapping the
whole stack to a LiteLLM proxy or any OpenAI-compatible provider is one
.env change, not a code change.
"""
from __future__ import annotations

import os

import instructor
from langchain_openai import ChatOpenAI
from openai import OpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import get_settings


def setup_langsmith() -> None:
    settings = get_settings()
    if settings.LANGCHAIN_TRACING_V2 and settings.LANGCHAIN_API_KEY:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.LANGCHAIN_API_KEY
        os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT
    else:
        os.environ["LANGCHAIN_TRACING_V2"] = "false"


def get_chat_model(temperature: float = 0.2) -> ChatOpenAI:
    settings = get_settings()
    return ChatOpenAI(
        model=settings.CHAT_MODEL,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        temperature=temperature,
        timeout=60,
    )


def get_instructor_client() -> instructor.Instructor:
    settings = get_settings()
    raw_client = OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)
    return instructor.from_openai(raw_client, mode=instructor.Mode.TOOLS)


RETRYABLE_EXCEPTIONS = (TimeoutError, ConnectionError)


def llm_retry():
    """Shared retry policy for LLM calls: exponential backoff, bounded
    attempts, only on transient network/timeout classes — never retries on
    e.g. a 400 from a malformed request, which would just fail the same
    way again."""
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        reraise=True,
    )
