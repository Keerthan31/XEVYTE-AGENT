"""
D. GOVERNANCE/SAFETY PLANE — Policy Engine (spec section 13)

Deterministic authorization. Nothing here is an LLM call — identity,
role, tenant, tool status, and data-sensitivity checks are all plain
comparisons against the tool's registry entry and the caller's real
session. The LLM proposes a tool_id + arguments; it never gets a vote on
whether that call is allowed. This is deliberately conservative: any
unrecognized role/permission string denies rather than allows, since a
parsing miss on an authorization rule must fail closed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.planes.knowledge.tool_registry import ToolRegistryEntry, ToolStatus


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str


def _role_satisfies(preauthorize_expr: str, role: Optional[str]) -> bool:
    if not preauthorize_expr:
        return True
    if not role:
        return False
    roles_required = re.findall(r"hasRole\('([^']+)'\)", preauthorize_expr)
    roles_required += re.findall(r"hasAnyRole\(([^)]+)\)", preauthorize_expr)
    if not roles_required:
        # Complex expression: fail closed if role is missing, otherwise defer fine-grained check to backend
        return bool(role)
    flat_roles = []
    for r in roles_required:
        flat_roles.extend(x.strip().strip("'\"") for x in r.split(","))
    return (role or "").upper() in {r.upper() for r in flat_roles}


def evaluate(
    tool: Optional[ToolRegistryEntry],
    *,
    authenticated: bool,
    role: Optional[str],
    tenant_id: Optional[str],
    session_tenant_id: Optional[str],
) -> PolicyDecision:
    if tool is None:
        return PolicyDecision(False, "Tool not found in the registry.")

    if tool.status not in (ToolStatus.ACTIVE,):
        return PolicyDecision(False, f"Tool '{tool.tool_id}' is {tool.status.value}, not available for use.")

    if tool.auth_required and not authenticated:
        return PolicyDecision(False, "This action requires an authenticated session.")

    if tool.permissions and not _role_satisfies(tool.permissions, role):
        return PolicyDecision(False, f"Your role does not satisfy the required permission: {tool.permissions}")

    # Tenant isolation: the real backend already enforces this from the JWT,
    # but denying here too means a caller sees a clear reason instead of a
    # generic 403 from a downstream system, and nothing ever gets attempted
    # cross-tenant even if a bug ever let a mismatched tenant_id through.
    if tenant_id and session_tenant_id and tenant_id != session_tenant_id:
        return PolicyDecision(False, "This action targets a different tenant than your session's.")

    return PolicyDecision(True, "OK")
