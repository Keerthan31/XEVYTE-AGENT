"""
B.3.2 DOMAIN ROUTER (Agent Control Plane)

Reduces the candidate space BEFORE tool discovery runs. Instead of hybrid
search scanning all 633 endpoints / 84 modules, the Intent Engine classifies
a coarse domain first (LEAVE, PAYROLL, ASSETS, ...) and the domain router
narrows the module set tool_discovery.py searches within to just that
domain's modules — smaller, more precise candidate pool, cheaper search.

The module -> domain mapping below is derived from (and validated against)
the real 84 modules in app/catalog/endpoint_catalog.json — every module is
accounted for, none silently dropped. If the Intent Engine returns a domain
with low confidence or "UNKNOWN", the router degrades gracefully to
searching all modules rather than guessing wrong and hiding real matches.
"""
from __future__ import annotations

from enum import Enum

from app.catalog.loader import get_catalog


class Domain(str, Enum):
    LEAVE = "LEAVE"
    ATTENDANCE = "ATTENDANCE"
    PAYROLL = "PAYROLL"
    TAX_DECLARATIONS = "TAX_DECLARATIONS"
    EMPLOYEE_PROFILE = "EMPLOYEE_PROFILE"
    ONBOARDING = "ONBOARDING"
    EXIT_OFFBOARDING = "EXIT_OFFBOARDING"
    PERFORMANCE = "PERFORMANCE"
    ASSETS = "ASSETS"
    SUPPORT = "SUPPORT"  # tickets + grievances
    TRAVEL = "TRAVEL"
    CLAIMS = "CLAIMS"
    ORG_STRUCTURE = "ORG_STRUCTURE"
    DOCUMENTS_KNOWLEDGE = "DOCUMENTS_KNOWLEDGE"
    NOTIFICATIONS = "NOTIFICATIONS"
    PROJECTS = "PROJECTS"
    ACCESS_ADMIN = "ACCESS_ADMIN"
    SYSTEM = "SYSTEM"
    UNKNOWN = "UNKNOWN"  # explicit escape hatch — never guess, search everything instead


DOMAIN_MODULES: dict[Domain, list[str]] = {
    Domain.LEAVE: ["Leave", "LeaveAssignment", "LeaveBalanceAdmin", "LeaveDraft", "Holiday", "AdminLeavePolicy"],
    Domain.ATTENDANCE: ["DailyEntry", "TaskCount", "AttendanceAnalytics"],
    Domain.PAYROLL: ["Payroll", "PayrollManagement", "Payslip", "SalaryComponent", "CompensationDetails", "CalcStructure", "TestRounding", "TestTransaction"],
    Domain.TAX_DECLARATIONS: ["ITDeclaration", "ITDeclarationCard", "ITDeclarationConfig", "ITDeclarationField"],
    Domain.EMPLOYEE_PROFILE: ["Employee", "EmployeeSummary", "Profiler", "InsuranceNominee", "EmployeeHandbook", "Department"],
    Domain.ONBOARDING: ["PreOnboarding", "Applicant", "ApplicantDocuments", "OfferLetter", "AppointmentLetter", "CandidateGeneralSettings", "OnboardingAuth"],
    Domain.EXIT_OFFBOARDING: ["Resignation", "ExitForm", "ExitAnswers", "PublicExitForm", "Clearance", "ClearanceChecklist"],
    Domain.PERFORMANCE: ["PerformanceAttribute", "PerformanceDepartment", "PerformanceGoal", "PerformanceGoalTemplate", "SelfAssessment"],
    Domain.ASSETS: ["AssetAllocation", "AssetAudit", "AssetCategory", "AssetDropdownOption", "AssetMaster", "AllCategories", "Allocation"],
    Domain.SUPPORT: ["Ticket", "HelpDeskCategory", "HelpDeskTeamAccess", "Grievance", "AdminGrievance"],
    Domain.TRAVEL: ["TravelRequest", "TravelRequestDraft"],
    Domain.CLAIMS: ["Claim"],
    Domain.ORG_STRUCTURE: ["OrgChart", "OrgChartConfig", "DesignationCategory", "CompanyLocation", "Location"],
    Domain.DOCUMENTS_KNOWLEDGE: ["Workflow", "PolicyAcknowledgment", "KnowledgeHub", "LMS", "WorkflowEngine"],
    Domain.NOTIFICATIONS: ["Notification"],
    Domain.PROJECTS: ["Project", "Customer", "Sow"],
    Domain.ACCESS_ADMIN: ["Role", "RoleAccess", "AdminAccess", "ModuleAccess", "Delegation"],
    Domain.SYSTEM: ["Health", "Audit", "Email", "ExternalApi", "RevisionType", "Auth", "Analytics", "UnifiedAnalytics"],
}

_MODULE_TO_DOMAIN: dict[str, Domain] = {m: d for d, mods in DOMAIN_MODULES.items() for m in mods}


def domain_for_module(module: str) -> Domain:
    return _MODULE_TO_DOMAIN.get(module, Domain.UNKNOWN)


def modules_for_domain(domain: Domain) -> list[str]:
    return DOMAIN_MODULES.get(domain, [])


def route(domain: Domain | str | None) -> list[str] | None:
    """Returns the module allow-list to constrain tool discovery to, or
    None (meaning "search everything") when the domain is UNKNOWN/unset —
    this is the deliberate fail-open-to-full-search behavior: a wrong
    narrow domain would hide the right tool, so low-confidence/unknown
    domain degrades to unconstrained search rather than a bad guess."""
    if domain is None:
        return None
    if isinstance(domain, str):
        try:
            domain = Domain(domain.upper())
        except ValueError:
            return None
    if domain == Domain.UNKNOWN:
        return None
    return modules_for_domain(domain) or None


def validate_coverage() -> dict:
    """Every real module must map to a domain — called at startup / by
    tests so a newly-discovered module (via the auto-refresh watcher)
    never silently falls through domain routing uncovered."""
    catalog = get_catalog()
    real_modules = set(catalog.modules())
    mapped_modules = set(_MODULE_TO_DOMAIN.keys())
    unmapped = real_modules - mapped_modules
    stale = mapped_modules - real_modules
    return {"unmapped_real_modules": sorted(unmapped), "stale_mapped_modules": sorted(stale)}
