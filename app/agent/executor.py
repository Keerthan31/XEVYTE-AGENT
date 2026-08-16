"""
The piece that makes "one agent, 600+ endpoints" actually work: a single
generic function that can call *any* endpoint in the catalog given its
spec plus the arguments the planner extracted. There is deliberately no
per-endpoint code anywhere in this system — every one of the 633
discovered endpoints is invoked through this same path.
"""
from __future__ import annotations

import time
from urllib.parse import quote

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.catalog.loader import EndpointSpec
from app.config import get_settings
from app.planes.execution.request_compiler import CompiledRequest

RESPONSE_BODY_CHAR_LIMIT = 12000  # keep huge list/report responses from blowing the LLM context


class ExecutionError(Exception):
    pass


def _build_path(endpoint: EndpointSpec, path_args: dict) -> str:
    path = endpoint.path
    for p in endpoint.path_params:
        name = p["name"]
        if name not in path_args or path_args[name] in (None, ""):
            raise ExecutionError(f"Missing required path parameter '{name}' for {endpoint.id}")
        path = path.replace("{" + name + "}", quote(str(path_args[name]), safe=""))
    return path


def _build_query(endpoint: EndpointSpec, query_args: dict) -> dict:
    out = {}
    for p in endpoint.query_params:
        name = p["name"]
        if name in query_args and query_args[name] not in (None, ""):
            out[name] = query_args[name]
        elif p.get("default") is not None:
            out[name] = p["default"]
        elif p.get("required"):
            raise ExecutionError(f"Missing required query parameter '{name}' for {endpoint.id}")
    return out


async def _send_with_retry(client: httpx.AsyncClient, request_kwargs: dict, idempotent: bool = False) -> httpx.Response:
    method = request_kwargs.get("method", "GET").upper()
    is_safe_method = method in ("GET", "HEAD", "OPTIONS") or idempotent

    max_attempts = 3 if is_safe_method else 1
    attempt = 0
    last_exc = None

    while attempt < max_attempts:
        attempt += 1
        try:
            return await client.request(**request_kwargs)
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as e:
            last_exc = e
            if attempt < max_attempts:
                import asyncio
                await asyncio.sleep(2 ** attempt)
            else:
                raise last_exc


async def execute_compiled(compiled: CompiledRequest, idempotent: bool = False) -> dict:
    """Executes a pre-compiled HTTP request built by RequestCompiler."""
    settings = get_settings()
    url = settings.HRMS_API_BASE_URL.rstrip("/") + compiled.url_path

    request_kwargs: dict = {
        "method": compiled.method,
        "url": url,
        "params": compiled.params,
        "headers": compiled.headers,
    }
    if compiled.json_body is not None:
        request_kwargs["json"] = compiled.json_body
    if compiled.data is not None:
        request_kwargs["data"] = compiled.data
    if compiled.files is not None:
        request_kwargs["files"] = compiled.files

    start = time.perf_counter()
    async with httpx.AsyncClient(timeout=settings.HRMS_API_TIMEOUT_SECONDS) as client:
        try:
            resp = await _send_with_retry(client, request_kwargs, idempotent=idempotent)
        except httpx.HTTPError as e:
            return {
                "status_code": None,
                "ok": False,
                "body": None,
                "error": f"Network error calling {compiled.method} {compiled.url_path}: {e}",
                "latency_ms": int((time.perf_counter() - start) * 1000),
            }
    latency_ms = int((time.perf_counter() - start) * 1000)

    content_type = resp.headers.get("content-type", "")
    try:
        parsed_body = resp.json() if "application/json" in content_type else resp.text
    except ValueError:
        parsed_body = resp.text

    if isinstance(parsed_body, str) and len(parsed_body) > RESPONSE_BODY_CHAR_LIMIT:
        parsed_body = parsed_body[:RESPONSE_BODY_CHAR_LIMIT] + "...[truncated]"

    return {
        "status_code": resp.status_code,
        "ok": resp.is_success,
        "body": parsed_body,
        "error": None if resp.is_success else f"HTTP {resp.status_code}",
        "latency_ms": latency_ms,
    }


async def execute(
    endpoint: EndpointSpec,
    path_args: dict | None = None,
    query_args: dict | None = None,
    body: object = None,
    bearer_token: str | None = None,
    files: dict | None = None,
) -> dict:
    """Executes one HRMS API call. Never raises for ordinary HTTP error
    statuses (4xx/5xx) — those come back as a normal result with ok=False
    so the response-generation node can explain them in plain language.
    Raises ExecutionError only for a malformed call (missing required
    params) that never should have reached this layer if the planner did
    its job — those are genuine bugs, not user-facing HTTP outcomes."""
    from app.planes.knowledge.tool_registry import build_entry
    from app.planes.execution.request_compiler import RequestCompiler

    tool = build_entry(endpoint)
    executable_arguments = {}
    if path_args:
        executable_arguments.update(path_args)
    if query_args:
        executable_arguments.update(query_args)
    if isinstance(body, dict):
        executable_arguments.update(body)

    compiled = RequestCompiler.compile(
        tool,
        executable_arguments,
        bearer_token=bearer_token,
        file_inputs=files,
    )
    if body is not None and not isinstance(body, dict):
        compiled.json_body = body

    return await execute_compiled(compiled, idempotent=(endpoint.http_method == "GET"))

