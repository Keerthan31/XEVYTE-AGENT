"""
D. GOVERNANCE/SAFETY PLANE — Risk Engine (spec section 14)

Classifies every tool call into READ / LOW_RISK_WRITE / HIGH_RISK_WRITE /
DESTRUCTIVE. The underlying heuristics (HTTP method + sensitive-module +
destructive/bulk path hints) are unchanged from the original, already-
validated risk.py — this module just re-expresses them under the 4-tier
naming the enterprise spec requires and separates "what tier is this"
(here) from "does this tier require approval" (policy_engine.py), so
policy can evolve independently of risk classification.
"""
from __future__ import annotations

from enum import Enum

from app.catalog.loader import EndpointSpec


class RiskTier(str, Enum):
    READ = "READ"
    LOW_RISK_WRITE = "LOW_RISK_WRITE"
    HIGH_RISK_WRITE = "HIGH_RISK_WRITE"
    DESTRUCTIVE = "DESTRUCTIVE"


_TIER_ORDER = {RiskTier.READ: 0, RiskTier.LOW_RISK_WRITE: 1, RiskTier.HIGH_RISK_WRITE: 2, RiskTier.DESTRUCTIVE: 3}

CRITICAL_WRITE_MODULES = {
    "payroll", "payrollmanagement", "salarycomponent", "compensationdetails",
    "roleaccess", "role", "moduleaccess", "adminaccess",
}
CRITICAL_PATH_HINTS = ("release-payslips", "generate-payslip", "/permanent", "bulk-excel")


def classify_risk(endpoint: EndpointSpec) -> RiskTier:
    method = endpoint.http_method.upper()
    module_lower = endpoint.module.lower()
    path_lower = endpoint.path.lower()

    if method == "GET":
        # sensitive reads (bank/PAN/salary/etc.) still get flagged one tier
        # up so they're logged and visible, without demanding approval for
        # every single read in the HR/payroll modules.
        return RiskTier.LOW_RISK_WRITE if endpoint.sensitive_module_hint else RiskTier.READ

    if module_lower in CRITICAL_WRITE_MODULES or any(h in path_lower for h in CRITICAL_PATH_HINTS):
        return RiskTier.DESTRUCTIVE
    if method == "DELETE" and endpoint.sensitive_module_hint:
        return RiskTier.DESTRUCTIVE
    if method == "DELETE":
        return RiskTier.HIGH_RISK_WRITE
    if endpoint.bulk_hint and endpoint.sensitive_module_hint:
        return RiskTier.DESTRUCTIVE
    if endpoint.bulk_hint or endpoint.sensitive_module_hint:
        return RiskTier.HIGH_RISK_WRITE

    return RiskTier.LOW_RISK_WRITE


def requires_approval(tier: RiskTier, threshold: RiskTier = RiskTier.HIGH_RISK_WRITE) -> bool:
    return _TIER_ORDER[tier] >= _TIER_ORDER[threshold]


def is_write(tier: RiskTier) -> bool:
    return tier != RiskTier.READ


def is_destructive(tier: RiskTier) -> bool:
    return tier == RiskTier.DESTRUCTIVE
