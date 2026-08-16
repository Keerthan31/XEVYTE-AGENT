"""
C. CONTEXT/KNOWLEDGE PLANE — Tool Registry (spec section 5)

A ToolRegistryEntry is the machine-readable "complete contract" for one
tool. This is built as an ENRICHMENT layer over the existing, already-
validated EndpointSpec catalog (app/catalog/loader.py) rather than a
rewrite — the parser that produces endpoint_catalog.json is unchanged and
still the single source of truth for "what endpoints exist"; this module
adds the governance/lifecycle fields the enterprise spec requires
(capabilities, domain, risk, approval requirement, idempotency, retry
policy, version, owner, status) on top.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from app.catalog.loader import Catalog, EndpointSpec, get_catalog
from app.planes.control.domain_router import Domain, domain_for_module
from app.planes.governance.risk_engine import RiskTier, classify_risk


class ToolStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    REGISTERED = "REGISTERED"
    VALIDATED = "VALIDATED"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    DISABLED = "DISABLED"
    RETIRED = "RETIRED"


# Explicit overrides for tools that should NOT be ACTIVE by default even
# though they parsed cleanly — e.g. internal test/debug endpoints found in
# the real controllers. Keyed by endpoint id substring; extend as needed.
_STATUS_OVERRIDES: dict[str, ToolStatus] = {
    "testrounding": ToolStatus.DISABLED,
    "testtransaction": ToolStatus.DISABLED,
    "_deep_test_": ToolStatus.DISABLED,
}


def _idempotent(endpoint: EndpointSpec) -> bool:
    # GET/PUT/DELETE are idempotent by HTTP semantics (repeating them has
    # the same end-state effect); POST/PATCH generally are not unless the
    # endpoint was explicitly designed with a client-supplied dedup key,
    # which nothing in this catalog currently does.
    return endpoint.http_method in ("GET", "PUT", "DELETE")


def _capability_name(endpoint: EndpointSpec) -> str:
    """'leave.apply', 'assetCategory.delete' style capability id — the
    human/semantic name the Capability Graph and Intent Engine's intent
    mappings refer to, one level above the raw tool_id."""
    action = endpoint.method_name[0].lower() + endpoint.method_name[1:]
    return f"{endpoint.module[0].lower()}{endpoint.module[1:]}.{action}"


@dataclass
class ToolRegistryEntry:
    tool_id: str
    name: str
    description: str
    domain: Domain
    module: str
    capability: str
    endpoint: str
    http_method: str
    request_schema: Optional[list[dict]]
    response_schema: Optional[dict]
    required_parameters: list[dict]
    optional_parameters: list[dict]
    header_parameters: list[dict] = field(default_factory=list)
    multipart_parts: list[dict] = field(default_factory=list)
    file_parameters: list[dict] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    permissions: Optional[str] = None
    risk_level: RiskTier = RiskTier.READ
    approval_required: bool = False
    idempotent: bool = False
    timeout_seconds: float = 30.0
    retry_policy: dict = field(default_factory=dict)
    version: str = ""
    owner: str = ""
    status: ToolStatus = ToolStatus.ACTIVE
    auth_required: bool = True
    has_file_upload: bool = False
    consumes: str = "application/json"
    produces: str = "application/json"
    wire_formats: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {**self.__dict__}
        d["domain"] = self.domain.value
        d["risk_level"] = self.risk_level.value
        d["status"] = self.status.value
        return d


def _content_version(endpoint: EndpointSpec) -> str:
    """Deterministic version tag derived from the endpoint's own shape —
    changes automatically when the Java signature changes (new params,
    new body fields), without needing anyone to hand-bump a version
    number. Short hash, not a semver — this is a change-detection tag,
    not a promise of semver compatibility."""
    basis = f"{endpoint.http_method}:{endpoint.path}:{endpoint.path_params}:{endpoint.query_params}:{endpoint.request_body_schema}"
    return hashlib.sha256(basis.encode()).hexdigest()[:10]


def build_entry(endpoint: EndpointSpec) -> ToolRegistryEntry:
    from app.planes.governance.risk_engine import requires_approval

    risk = classify_risk(endpoint)
    status = ToolStatus.ACTIVE
    for key, override in _STATUS_OVERRIDES.items():
        if key in endpoint.id.lower():
            status = override
            break

    non_file_q = endpoint.non_file_query_params()
    file_q = endpoint.file_query_params()
    required = [p for p in non_file_q if p.get("required")] + list(endpoint.path_params)
    optional = [p for p in non_file_q if not p.get("required")]

    return ToolRegistryEntry(
        tool_id=endpoint.id,
        name=endpoint.method_name,
        description=endpoint.embedding_text() or endpoint.description,
        domain=domain_for_module(endpoint.module),
        module=endpoint.module,
        capability=_capability_name(endpoint),
        endpoint=endpoint.path,
        http_method=endpoint.http_method,
        request_schema=endpoint.request_body_schema,
        response_schema=None,  # Java controllers don't declare response DTOs uniformly enough to statically resolve; see result_validator.py for runtime-side handling instead
        required_parameters=required,
        optional_parameters=optional,
        header_parameters=endpoint.header_params or [],
        multipart_parts=endpoint.get_multipart_parts() or [],
        file_parameters=file_q,
        dependencies=[],  # populated by capability_graph.py for tools with known prerequisite calls
        permissions=endpoint.preauthorize,
        risk_level=risk,
        approval_required=requires_approval(risk),
        idempotent=_idempotent(endpoint),
        timeout_seconds=30.0,
        retry_policy={"max_attempts": 3 if endpoint.http_method == "GET" else 1, "backoff": "exponential"},
        version=_content_version(endpoint),
        owner=f"module:{endpoint.module}",
        status=status,
        auth_required=endpoint.auth_required,
        has_file_upload=endpoint.has_file_upload,
        consumes=endpoint.consumes,
        produces=endpoint.produces,
        wire_formats=endpoint.wire_formats or {},
    )


class ToolRegistry:
    def __init__(self, catalog: Optional[Catalog] = None):
        self._catalog = catalog or get_catalog()
        self._entries: dict[str, ToolRegistryEntry] = {
            e.id: build_entry(e) for e in self._catalog.endpoints
        }
        self.generated_at = datetime.now(timezone.utc)

    def get(self, tool_id: str) -> Optional[ToolRegistryEntry]:
        entry = self._entries.get(tool_id)
        return entry if entry and entry.status not in (ToolStatus.DISABLED, ToolStatus.RETIRED) else None

    def get_raw(self, tool_id: str) -> Optional[ToolRegistryEntry]:
        """Includes disabled/retired entries — for admin/debug views only,
        never for the execution path (use .get())."""
        return self._entries.get(tool_id)

    def all_active(self) -> list[ToolRegistryEntry]:
        return [e for e in self._entries.values() if e.status == ToolStatus.ACTIVE]

    def by_domain(self, domain: Domain) -> list[ToolRegistryEntry]:
        return [e for e in self.all_active() if e.domain == domain]

    def by_capability(self, capability: str) -> Optional[ToolRegistryEntry]:
        for e in self.all_active():
            if e.capability == capability:
                return e
        return None

    def __len__(self) -> int:
        return len(self._entries)


_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def reload_tool_registry() -> ToolRegistry:
    global _registry
    _registry = ToolRegistry()
    return _registry
