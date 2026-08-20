"""
Dynamic OpenAPI Catalog Loader.

On startup, fetches the live OpenAPI 3.x JSON from the Java backend
and builds a searchable catalog of every endpoint.  If the Java team
adds new controllers the agent automatically learns them — zero manual
intervention required.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from app.catalog.models import (
    CatalogEntry,
    EndpointParameter,
    ParamLocation,
    RiskTier,
)
from app.config import get_settings

logger = logging.getLogger("xeva.catalog")

# ── Admin-only / destructive paths the agent must NEVER call ──
BLOCKED_PATH_PATTERNS: list[re.Pattern] = [
    re.compile(r"/api/external/"),
    re.compile(r"/api/test/"),
    re.compile(r"/api/v1/auth/"),
    re.compile(r"/api/auth/"),
    re.compile(r"/api/admin/"),
    re.compile(r"/api/v1/admin-access/"),
]


def _classify_risk(method: str, path: str) -> RiskTier:
    """Auto-classify risk tier based on HTTP method and path patterns."""
    for pattern in BLOCKED_PATH_PATTERNS:
        if pattern.search(path):
            return RiskTier.BLOCKED

    upper = method.upper()
    if upper == "GET":
        return RiskTier.SAFE
    if upper in ("POST", "PUT", "PATCH", "DELETE"):
        return RiskTier.CONFIRM
    return RiskTier.SAFE


def _generate_endpoint_id(path: str, method: str, operation: dict) -> str:
    """
    Build a human-readable endpoint_id from operationId or path.
    e.g.  LeaveController.applyLeave  or  leaves_apply_POST
    """
    op_id = operation.get("operationId")
    if op_id:
        # Spring Boot format: applyLeave_1  → remove trailing _N
        op_id = re.sub(r"_\d+$", "", op_id)
        return op_id

    # Fallback: build from path
    clean = path.replace("/api/", "").replace("/", "_").strip("_")
    return f"{clean}_{method.upper()}"


def _parse_parameters(raw_params: list[dict]) -> list[EndpointParameter]:
    """Convert OpenAPI parameter objects to our model."""
    params: list[EndpointParameter] = []
    for p in raw_params:
        loc_str = p.get("in", "query")
        try:
            loc = ParamLocation(loc_str)
        except ValueError:
            loc = ParamLocation.QUERY

        schema = p.get("schema", {})
        params.append(EndpointParameter(
            name=p.get("name", "unknown"),
            location=loc,
            required=p.get("required", False),
            schema_type=schema.get("type", "string"),
            description=p.get("description", ""),
            default=schema.get("default"),
            enum_values=schema.get("enum"),
        ))
    return params


def _extract_body_schema(operation: dict) -> tuple[dict | None, str]:
    """Extract request body JSON schema (if any)."""
    rb = operation.get("requestBody")
    if not rb:
        return None, "application/json"

    content = rb.get("content", {})

    # Prefer JSON
    for ct in ("application/json", "multipart/form-data", "*/*"):
        if ct in content:
            schema = content[ct].get("schema", {})
            return schema, ct

    # Fallback: first content type
    if content:
        first_ct = next(iter(content))
        return content[first_ct].get("schema", {}), first_ct

    return None, "application/json"


def _resolve_refs(schema: dict, components: dict, depth: int = 0) -> dict:
    """Inline-resolve $ref pointers with a max depth to avoid circular reference crashes."""
    if not schema or depth > 3:
        return schema

    ref = schema.get("$ref")
    if ref and ref.startswith("#/components/schemas/"):
        name = ref.split("/")[-1]
        resolved = components.get("schemas", {}).get(name, {})
        return _resolve_refs(resolved, components, depth + 1)

    # Resolve properties
    if "properties" in schema:
        resolved_props = {}
        for k, v in schema["properties"].items():
            resolved_props[k] = _resolve_refs(v, components, depth + 1)
        schema = {**schema, "properties": resolved_props}

    # Resolve items in arrays
    if "items" in schema:
        schema = {**schema, "items": _resolve_refs(schema["items"], components, depth + 1)}

    return schema


def _simplify_schema(schema: dict | None, components: dict) -> dict | None:
    """Turn a potentially complex schema into a simplified dict for the LLM."""
    if not schema:
        return None

    resolved = _resolve_refs(schema, components)

    if resolved.get("type") == "object" and "properties" in resolved:
        simple: dict[str, Any] = {}
        required_fields = set(resolved.get("required", []))
        for name, prop in resolved["properties"].items():
            prop_type = prop.get("type", "string")
            req_mark = " (required)" if name in required_fields else ""
            desc = prop.get("description", "")
            enum = prop.get("enum")
            if enum:
                simple[name] = f"{prop_type}{req_mark} enum={enum}"
            elif desc:
                simple[name] = f"{prop_type}{req_mark} – {desc}"
            else:
                simple[name] = f"{prop_type}{req_mark}"
        return simple

    return resolved


# ─────────────────────────────────────────────────────────────
#  PUBLIC API
# ─────────────────────────────────────────────────────────────

async def load_catalog_from_spec() -> dict[str, CatalogEntry]:
    """
    Fetch the live OpenAPI JSON from the Java backend and build the catalog.
    Returns a dict keyed by endpoint_id.
    """
    settings = get_settings()
    url = settings.OPENAPI_SPEC_URL
    logger.info("Loading OpenAPI spec from %s …", url)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            spec = resp.json()
    except Exception as exc:
        logger.warning(
            "Could not fetch OpenAPI spec from %s: %s. "
            "Falling back to empty catalog — the agent will still work "
            "but cannot auto-discover Java API endpoints.",
            url, exc,
        )
        return {}

    return parse_openapi_spec(spec)


def parse_openapi_spec(spec: dict) -> dict[str, CatalogEntry]:
    """Parse an OpenAPI 3.x dict into a catalog of CatalogEntry objects."""
    catalog: dict[str, CatalogEntry] = {}
    components = spec.get("components", {})
    paths = spec.get("paths", {})

    for path, methods in paths.items():
        # Shared parameters at path level
        shared_params = methods.get("parameters", [])

        for method in ("get", "post", "put", "delete", "patch"):
            operation = methods.get(method)
            if not operation:
                continue

            endpoint_id = _generate_endpoint_id(path, method, operation)
            risk = _classify_risk(method, path)

            # Merge shared + operation params
            all_params = shared_params + operation.get("parameters", [])
            parameters = _parse_parameters(all_params)

            body_schema_raw, body_ct = _extract_body_schema(operation)
            body_schema = _simplify_schema(body_schema_raw, components)

            entry = CatalogEntry(
                endpoint_id=endpoint_id,
                method=method.upper(),
                path=path,
                summary=operation.get("summary", ""),
                description=operation.get("description", ""),
                tags=operation.get("tags", []),
                parameters=parameters,
                request_body_schema=body_schema,
                request_body_content_type=body_ct,
                risk_tier=risk,
            )
            entry.build_search_text()
            catalog[endpoint_id] = entry

    logger.info(
        "Catalog loaded: %d endpoints (%d safe, %d confirm, %d blocked)",
        len(catalog),
        sum(1 for e in catalog.values() if e.risk_tier == RiskTier.SAFE),
        sum(1 for e in catalog.values() if e.risk_tier == RiskTier.CONFIRM),
        sum(1 for e in catalog.values() if e.risk_tier == RiskTier.BLOCKED),
    )
    return catalog


def build_fallback_catalog() -> dict[str, CatalogEntry]:
    """
    Hardcoded fallback catalog for the most critical endpoints.
    Used when the Java backend is offline during agent startup.
    """
    entries: list[dict] = [
        {"endpoint_id": "submitEntry", "method": "POST", "path": "/api/daily-entry/submit/{employeeId}", "summary": "Check in / punch in for daily attendance", "tags": ["attendance"]},
        {"endpoint_id": "updateEntry", "method": "PUT", "path": "/api/daily-entry/update/{entryId}", "summary": "Check out / punch out — update logout time", "tags": ["attendance"]},
        {"endpoint_id": "getEmployeeEntries", "method": "GET", "path": "/api/daily-entry/employee/{employeeId}", "summary": "View attendance history for an employee", "tags": ["attendance"]},
        {"endpoint_id": "getTotalHours", "method": "GET", "path": "/api/daily-entry/total-hours/{employeeId}", "summary": "Get total hours worked for an employee", "tags": ["attendance"]},
        {"endpoint_id": "getSubmittedDates", "method": "GET", "path": "/api/daily-entry/submitted-dates/{employeeId}", "summary": "Get dates with submitted attendance", "tags": ["attendance"]},
        {"endpoint_id": "applyLeave", "method": "POST", "path": "/api/leaves/apply", "summary": "Apply for leave", "tags": ["leaves"]},
        {"endpoint_id": "getEmployeeLeaves", "method": "GET", "path": "/api/leaves/employee/{employeeId}", "summary": "View employee leave requests", "tags": ["leaves"]},
        {"endpoint_id": "cancelLeave", "method": "PUT", "path": "/api/leaves/cancel/{id}", "summary": "Cancel a leave request", "tags": ["leaves"]},
        {"endpoint_id": "takeAction", "method": "POST", "path": "/api/leaves/action", "summary": "Approve or reject a leave request (manager)", "tags": ["leaves"]},
        {"endpoint_id": "getManagerLeaves", "method": "GET", "path": "/api/leaves/manager/{managerId}", "summary": "View team leave requests (manager)", "tags": ["leaves"]},
        {"endpoint_id": "getLeaveTypes", "method": "GET", "path": "/api/leaves/types", "summary": "List all leave types", "tags": ["leaves"]},
        {"endpoint_id": "getLeaveBalance", "method": "GET", "path": "/api/leaves/balance/{employeeId}", "summary": "Check leave balance for an employee", "tags": ["leaves"]},
        {"endpoint_id": "getHolidays", "method": "GET", "path": "/api/v1/holidays", "summary": "List holidays for a year", "tags": ["holidays"]},
        {"endpoint_id": "submitClaim", "method": "POST", "path": "/api/claims", "summary": "Submit an expense / reimbursement claim", "tags": ["claims"]},
        {"endpoint_id": "getMyClaims", "method": "GET", "path": "/api/claims/employee/{employeeId}", "summary": "View employee claims", "tags": ["claims"]},
        {"endpoint_id": "getPayslip", "method": "GET", "path": "/api/v1/payslips/{employeeId}", "summary": "Get payslip for employee", "tags": ["payroll"]},
        {"endpoint_id": "submitTicket", "method": "POST", "path": "/api/tickets", "summary": "Raise a helpdesk support ticket", "tags": ["tickets"]},
        {"endpoint_id": "getMyTickets", "method": "GET", "path": "/api/tickets/employee/{employeeId}", "summary": "View employee tickets", "tags": ["tickets"]},
        {"endpoint_id": "submitGrievance", "method": "POST", "path": "/api/grievances", "summary": "Submit an anonymous grievance", "tags": ["grievances"]},
        {"endpoint_id": "getGoals", "method": "GET", "path": "/api/goals/employee/{employeeId}", "summary": "Get performance goals for an employee", "tags": ["performance"]},
        {"endpoint_id": "getMyAssets", "method": "GET", "path": "/api/assets/allocations/employee/{employeeId}", "summary": "View allocated company assets", "tags": ["assets"]},
        {"endpoint_id": "getOrgChart", "method": "GET", "path": "/api/employees/org-chart/{employeeId}", "summary": "View organisation chart", "tags": ["org"]},
        {"endpoint_id": "getEmployeeProfile", "method": "GET", "path": "/api/employees/{employeeId}", "summary": "Get employee profile details", "tags": ["profile"]},
        {"endpoint_id": "getNotifications", "method": "GET", "path": "/api/notifications/{employeeId}", "summary": "Get employee notifications", "tags": ["notifications"]},
        {"endpoint_id": "getTaskCounts", "method": "GET", "path": "/api/task-counts/{employeeId}", "summary": "Get pending task counts (unified inbox)", "tags": ["tasks"]},
        {"endpoint_id": "getDeclarations", "method": "GET", "path": "/api/it-declarations/employee/{employeeId}", "summary": "Get IT declarations for an employee", "tags": ["payroll"]},
        {"endpoint_id": "submitResignation", "method": "POST", "path": "/api/v1/exit-management/submit", "summary": "Submit a resignation", "tags": ["resignation"]},
        {"endpoint_id": "getKnowledgeHub", "method": "GET", "path": "/api/knowledge-hub", "summary": "Search knowledge base articles", "tags": ["knowledge"]},
        {"endpoint_id": "getProjects", "method": "GET", "path": "/api/projects", "summary": "List projects", "tags": ["projects"]},
        {"endpoint_id": "getDelegations", "method": "GET", "path": "/api/delegations/employee/{employeeId}", "summary": "View active delegations", "tags": ["delegations"]},
        {"endpoint_id": "submitTravelRequest", "method": "POST", "path": "/api/travel", "summary": "Submit a travel request", "tags": ["travel"]},
        {"endpoint_id": "getApprovedDates", "method": "GET", "path": "/api/leaves/approved-dates/{employeeId}", "summary": "Get approved leave dates", "tags": ["leaves"]},
        {"endpoint_id": "getCompensation", "method": "GET", "path": "/api/compensation/{employeeId}", "summary": "Get compensation / CTC breakdown", "tags": ["payroll"]},
    ]

    catalog: dict[str, CatalogEntry] = {}
    for e in entries:
        entry = CatalogEntry(
            endpoint_id=e["endpoint_id"],
            method=e["method"],
            path=e["path"],
            summary=e.get("summary", ""),
            tags=e.get("tags", []),
            risk_tier=_classify_risk(e["method"], e["path"]),
        )
        entry.build_search_text()
        catalog[entry.endpoint_id] = entry

    logger.info("Fallback catalog loaded with %d core endpoints", len(catalog))
    return catalog
