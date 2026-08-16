"""
E. EXECUTION PLANE — API Execution Fabric (spec section 17)

Wraps app/agent/executor.py's execute() — the already-tested generic HTTP
call (path/query substitution, multipart, auth header, tenacity retry) is
unchanged — with two things it didn't have: a per-module circuit breaker
(persisted, survives restarts) and idempotency-key protection on writes so
a retried POST/PUT/DELETE can't fire twice against the Java backend.

    "Do not retry unsafe operations blindly. For write operations,
    implement idempotency protection."
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from app.agent import executor as base_executor
from app.catalog.loader import EndpointSpec
from app.database import SessionLocal
from app.db_models import CircuitBreakerState, IdempotencyKey
from app.planes.knowledge.tool_registry import ToolRegistryEntry

FAILURE_THRESHOLD = 5          # consecutive failures before a module's breaker opens
OPEN_COOLDOWN_SECONDS = 60      # how long OPEN blocks calls before allowing a HALF_OPEN trial


class CircuitOpenError(Exception):
    pass


def _module_group(tool: ToolRegistryEntry) -> str:
    return tool.module


def _check_and_maybe_trip_open(db, module: str) -> str:
    state = db.get(CircuitBreakerState, module)
    if not state:
        state = CircuitBreakerState(tool_group=module, state="CLOSED", failure_count=0)
        db.add(state)
        db.commit()
        return "CLOSED"

    if state.state == "OPEN":
        elapsed = datetime.now(timezone.utc) - state.opened_at.replace(tzinfo=timezone.utc)
        if elapsed > timedelta(seconds=OPEN_COOLDOWN_SECONDS):
            state.state = "HALF_OPEN"
            db.commit()
            return "HALF_OPEN"
        return "OPEN"
    return state.state


def _record_result(db, module: str, success: bool) -> None:
    state = db.get(CircuitBreakerState, module)
    if not state:
        state = CircuitBreakerState(tool_group=module)
        db.add(state)

    if success:
        state.state = "CLOSED"
        state.failure_count = 0
        state.opened_at = None
    else:
        state.failure_count += 1
        if state.state == "HALF_OPEN" or state.failure_count >= FAILURE_THRESHOLD:
            state.state = "OPEN"
            state.opened_at = datetime.now(timezone.utc)
    db.commit()


def _idempotency_key(tool_id: str, arguments: dict, employee_id: str | None = None) -> str:
    canonical = json.dumps({"employee_id": employee_id, "tool_id": tool_id, "arguments": arguments}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _spec_from_entry(tool: ToolRegistryEntry, path_params: list[dict], query_params: list[dict]) -> EndpointSpec:
    """api_fabric operates on ToolRegistryEntry (the governance-plane view);
    the underlying executor still speaks EndpointSpec (the catalog view).
    Reconstructing the minimal EndpointSpec fields it actually reads keeps
    the tested executor untouched rather than forking its logic."""
    return EndpointSpec(
        id=tool.tool_id, module=tool.module, controller_class="", method_name=tool.name,
        http_method=tool.http_method, path=tool.endpoint, path_params=path_params, query_params=query_params,
        request_body_type=None, request_body_is_list=False, request_body_schema=tool.request_schema,
        consumes="multipart/form-data" if tool.has_file_upload else "application/json",
        has_file_upload=tool.has_file_upload, auth_required=tool.auth_required,
    )


async def execute_with_fabric(
    tool: ToolRegistryEntry,
    executable_arguments: dict,
    *,
    bearer_token: str | None,
    employee_id: str | None = None,
    files: dict | None = None,
) -> dict:
    module = _module_group(tool)
    db = SessionLocal()
    try:
        breaker = _check_and_maybe_trip_open(db, module)
        if breaker == "OPEN":
            return {"status_code": None, "ok": False, "body": None,
                    "error": f"circuit open for module '{module}' — too many recent failures, cooling down",
                    "latency_ms": 0, "circuit_breaker": "OPEN"}

        idem_key = None
        if tool.http_method in ("POST", "PUT", "DELETE", "PATCH"):
            idem_key = _idempotency_key(tool.tool_id, executable_arguments, employee_id)
            existing = db.get(IdempotencyKey, idem_key)
            if existing:
                return {**existing.response_snapshot, "idempotent_replay": True}

        from app.planes.execution.request_compiler import RequestCompiler
        compiled = RequestCompiler.compile(
            tool,
            executable_arguments,
            bearer_token=bearer_token,
            file_inputs=files,
        )

        result = await base_executor.execute_compiled(compiled)
        _record_result(db, module, success=result.get("ok", False))

        if idem_key and result.get("ok"):
            db.add(IdempotencyKey(key=idem_key, tool_id=tool.tool_id, response_snapshot=result))
            db.commit()

        return result
    finally:
        db.close()

