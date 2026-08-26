"""
Category 2: Intent Testing
Tests that Natural Language queries map to the expected endpoint_id and capability
across the 19 HRMS catalog modules and synonym expansions.
"""

import pytest
from app.agent.tools import APIECatalog, search_api_catalog


# ============================================================================
# Core Module Intent Tests
# ============================================================================

INTENT_TEST_CASES = [
    # 1. Attendance & Daily Entry
    ("Submit daily attendance entry", ["submitEntry", "submitDailyEntry"]),
    ("Punch in daily entry", ["submitEntry", "submitDailyEntry", "updateEntry"]),
    ("Punch out attendance", ["updateEntry", "updateDailyEntry"]),
    ("View employee daily attendance entries", ["getEmployeeEntries", "getDailyEntries"]),
    
    # 2. Leave Management
    ("Apply for 3 days of sick leave starting tomorrow", ["applyLeave"]),
    ("I need to take casual leave", ["applyLeave"]),
    ("Check my remaining leave balance", ["getDetailedLeaveBalance", "getLeaveBalance", "getEmployeeLeaves"]),
    ("Get employee leaves history", ["getEmployeeLeaves", "getMyLeaves"]),
    ("Approve the pending leave request", ["approveLeave", "takeAction"]),
    ("Cancel my approved leave", ["cancelLeave"]),
    
    # 3. Claims & Reimbursements
    ("Submit a new expense claim for travel", ["saveClaim", "submitClaim", "createClaim"]),
    ("Save a draft claim for 5000 rs hotel stay", ["saveClaim", "saveDraftClaim", "draftClaim", "saveDraft"]),
    ("View my past expense claims", ["getMyClaims", "getClaimsByEmployee", "getClaimHistory"]),
    ("Approve employee expense reimbursement", ["approveClaim", "takeActionOnClaim"]),
    
    # 4. Helpdesk & Tickets
    ("Raise a new IT support ticket for broken keyboard", ["submitTicket", "createTicket"]),
    ("Show my open tickets", ["getMyTickets", "getTicketsByEmployee", "getAllTickets"]),
    ("Check team tickets assigned to me", ["getTeamTickets", "getTicketsForManager"]),
    
    # 5. Asset Management
    ("Add a new laptop to the inventory", ["createAsset", "addAsset"]),
    ("List all available assets", ["getAvailableAssets", "getAllAssets"]),
    ("Allocate asset to employee", ["allocateAsset", "assignAsset"]),
    
    # 6. Exit & Resignation Management
    ("Submit my resignation letter", ["submitResignation", "initiateResignation"]),
    ("View my exit form status", ["getMyResignation", "getExitForms"]),
    
    # 7. Grievances
    ("File an anonymous grievance complaint", ["submitGrievance", "submitAnonymousGrievance", "createAnonymousGrievance"]),
    
    # 8. Employee Onboarding & Pre-Onboarding
    ("Onboard new employee single entry", ["onboardSingleEmployee", "createEmployee", "addEmployee"]),
    ("View pre-onboarding applicant list", ["getApplicants", "getAllApplicants"]),
    ("Send onboarding email link to applicant", ["sendOnboardingEmail"]),
    
    # 9. Performance Management
    ("Assign performance goal", ["assignGoal", "createGoal", "saveGoal"]),
    ("Get goals for employee", ["getGoalsForEmployee", "getGoals"]),
    
    # 10. Payroll & Compensation
    ("Generate payslips for August 2026", ["generatePayslips", "generatePayslipsForAll"]),
    ("Download my latest payslip", ["getPayslipsByEmployee", "downloadPayslipPdf", "getPayslip"]),
    ("View my compensation details", ["getCompensationDetails", "getByEmployeeId"]),
    
    # 11. IT Declarations
    ("Submit my IT declaration tax regime", ["saveOrUpdate", "saveITDeclaration"]),
    ("View my IT declaration for this year", ["getByEmployeeAndYear", "getByEmployee"]),
]


@pytest.mark.parametrize("query,expected_endpoint_ids", INTENT_TEST_CASES)
def test_search_by_intent_top_matches(query, expected_endpoint_ids):
    """Test that search_by_intent returns at least one of the expected endpoint IDs in top results."""
    results = APIECatalog.search_by_intent(query)
    assert len(results) > 0, f"No endpoints returned for query: '{query}'"
    
    top_ids = [ep.get("endpoint_id") for ep in results[:5]]
    matched = any(eid in top_ids for eid in expected_endpoint_ids)
    assert matched, (
        f"Query: '{query}'\n"
        f"Expected any of: {expected_endpoint_ids}\n"
        f"Got top IDs: {top_ids}"
    )


# ============================================================================
# Synonym & Keyword Expansion Tests
# ============================================================================

def test_synonym_expansion_client_customer():
    """Verify that 'client' and 'customer' query synonyms map to customer endpoints."""
    res_client = APIECatalog.search_by_intent("show all clients")
    res_customer = APIECatalog.search_by_intent("show all customers")
    
    client_ids = [ep.get("endpoint_id") for ep in res_client]
    customer_ids = [ep.get("endpoint_id") for ep in res_customer]
    
    # Both should contain customer endpoints like getAllCustomers
    assert any("Customer" in cid or "Client" in cid for cid in client_ids)
    assert any("Customer" in cid or "Client" in cid for cid in customer_ids)


def test_synonym_expansion_laptop_asset():
    """Verify that 'laptop' maps to asset management."""
    res = APIECatalog.search_by_intent("need a new laptop")
    ids = [ep.get("endpoint_id") for ep in res]
    assert any("asset" in eid.lower() or "asset" in str(ep.get("path")).lower() for ep, eid in zip(res, ids))


def test_synonym_expansion_ticket_incident():
    """Verify that 'incident' or 'issue' maps to ticket endpoints."""
    res = APIECatalog.search_by_intent("report network incident")
    ids = [ep.get("endpoint_id") for ep in res]
    assert any("ticket" in eid.lower() or "helpdesk" in str(ep.get("path")).lower() for ep, eid in zip(res, ids))


# ============================================================================
# Intent Verb Alignment (POST vs GET vs PUT/DELETE)
# ============================================================================

def test_intent_verb_alignment_create_vs_view():
    """Verify create intents prefer POST/PUT and view intents prefer GET."""
    create_res = APIECatalog.search_by_intent("create new leave policy")
    view_res = APIECatalog.search_by_intent("view current leave policy")
    
    assert len(create_res) > 0
    assert len(view_res) > 0
    
    # Top creation endpoint should be POST or have create/save in it
    top_create = create_res[0]
    assert top_create.get("method") in ("POST", "PUT") or "create" in top_create.get("endpoint_id", "").lower() or "save" in top_create.get("endpoint_id", "").lower()

    # Top view endpoint should be GET
    top_view = view_res[0]
    assert top_view.get("method") == "GET" or "get" in top_view.get("endpoint_id", "").lower() or "view" in top_view.get("endpoint_id", "").lower()


def test_search_api_catalog_tool_output_format():
    """Verify that the search_api_catalog tool returns structured string for LLM."""
    out = search_api_catalog("check my leaves")
    assert isinstance(out, str)
    assert "Tool Name:" in out or "Found the following" in out
    assert "CRITICAL RULES:" in out
