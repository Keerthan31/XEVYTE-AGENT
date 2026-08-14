"""
Classifies an endpoint call's risk tier so the agent knows when to just do
the thing vs. when to show the user exactly what it's about to call and
wait for an explicit yes.

Important: this is a UX/policy layer, NOT the security boundary. The real
security boundary is the Xevyte Connect backend itself — every call this
agent makes carries the user's own Scaloz IAM token, so the backend's
existing @PreAuthorize checks and tenant scoping apply exactly as they
would if the user clicked through the React UI. Guardrails here exist to
stop an LLM from doing something *irreversible or high-blast-radius* on
the user's behalf without them explicitly seeing and approving it first —
they narrow what an authorized user's own agent will do unprompted, not
what the backend allows them to do at all.
"""
from __future__ import annotations

from enum import Enum

from app.catalog.loader import EndpointSpec


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


_TIER_ORDER = {RiskTier.LOW: 0, RiskTier.MEDIUM: 1, RiskTier.HIGH: 2, RiskTier.CRITICAL: 3}

# Modules/paths where even a "read" can be sensitive, and where a write is
# treated as CRITICAL regardless of HTTP verb heuristics — money movement,
# access control, and irrevocable HR lifecycle actions.
CRITICAL_WRITE_MODULES = {
    "payroll", "payrollmanagement", "salarycomponent", "compensationdetails",
    "roleaccess", "role", "moduleaccess", "adminaccess",
}
CRITICAL_PATH_HINTS = ("release-payslips", "generate-payslip", "/permanent", "bulk-excel")


def classify(endpoint: EndpointSpec) -> RiskTier:
    method = endpoint.http_method.upper()
    module_lower = endpoint.module.lower()
    path_lower = endpoint.path.lower()

    if method == "GET":
        # A handful of GETs still return highly sensitive personal data
        # (bank details, PAN/Aadhaar, salary breakdowns) — keep those at
        # MEDIUM so they're logged and visible, without demanding a click
        # for every single read in the HR/payroll modules.
        if endpoint.sensitive_module_hint:
            return RiskTier.MEDIUM
        return RiskTier.LOW

    if module_lower in CRITICAL_WRITE_MODULES:
        return RiskTier.CRITICAL
    if any(h in path_lower for h in CRITICAL_PATH_HINTS):
        return RiskTier.CRITICAL

    if method == "DELETE" and endpoint.sensitive_module_hint:
        return RiskTier.CRITICAL
    if method == "DELETE":
        return RiskTier.HIGH
    if endpoint.bulk_hint and endpoint.sensitive_module_hint:
        return RiskTier.CRITICAL
    if endpoint.bulk_hint:
        return RiskTier.HIGH
    if endpoint.sensitive_module_hint:
        return RiskTier.HIGH

    # Plain POST/PUT/PATCH on a non-sensitive module (e.g. add an asset
    # category, apply for leave) — meaningful but ordinary and reversible.
    return RiskTier.MEDIUM


def requires_confirmation(tier: RiskTier, threshold: str) -> bool:
    try:
        threshold_tier = RiskTier(threshold.upper())
    except ValueError:
        threshold_tier = RiskTier.MEDIUM
    return _TIER_ORDER[tier] >= _TIER_ORDER[threshold_tier]
