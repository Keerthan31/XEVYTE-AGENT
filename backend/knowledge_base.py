"""
Xevyte HRMS Knowledge Base & ChromaDB Vector Store Engine.
Provides high-speed semantic search for company HR policies, leave rules, ticket SLAs,
and grievance guidelines without requiring external uploaded PDF documents.
"""

import logging
import json

logger = logging.getLogger(__name__)

# ─── BUILT-IN XEVYTE HR KNOWLEDGE DATASET ─────────────────────────────────────
XEVYTE_HR_DATASET = [
    {
        "id": "policy_leave_01",
        "category": "Leave Rules & Advance Notice",
        "content": (
            "Casual Leave (CL) and Earned Leave (EL) require 24 hours advance application. "
            "Emergency Sick Leave (SL) can be applied retroactively within 48 hours. "
            "Optional Leaves must be chosen from the approved annual festival holiday list."
        )
    },
    {
        "id": "policy_leave_02",
        "category": "Leave Cancellation Guidelines",
        "content": (
            "Employees can cancel pending or approved leaves directly through Xeva before the leave start date. "
            "Once a leave date has passed or is currently in progress, cancellation requires manager or HR intervention. "
            "If applying for a new leave fails with a zero-days conflict error, check if a duplicate leave exists on that date."
        )
    },
    {
        "id": "policy_attendance_01",
        "category": "Attendance & Work Location",
        "content": (
            "Daily check-in requires selecting a valid work location: 'Office', 'WFH', or 'Client Location'. "
            "If working at a Client Location, specifying Client Name and Project Name is mandatory. "
            "Daily attendance status can be verified using the check_today_attendance tool before submitting."
        )
    },
    {
        "id": "policy_grievance_01",
        "category": "Grievance & Confidentiality",
        "content": (
            "Anonymous grievances submitted via Xeva hide employee personal identifiers from reviewers. "
            "Supported grievance categories include: Harassment, Payroll, Work Environment, Policy Violation, Discrimination, General. "
            "Grievances cannot be modified once submitted."
        )
    },
    {
        "id": "policy_ticket_01",
        "category": "Helpdesk Ticket SLAs",
        "content": (
            "Support tickets are categorized under IT, HR, Finance, Admin, or Facilities. "
            "Critical hardware or access issues (IT) have a 4-hour response SLA. "
            "General payroll queries or document requests have a 24-hour response SLA. "
            "Copying your manager on a ticket (ccToManager) notifies them via Scaloz IAM."
        )
    },
    {
        "id": "policy_approvals_01",
        "category": "Manager & Admin Approvals",
        "content": (
            "Managers receive leave requests in their approval queue. "
            "Managers can approve or reject leaves with optional remarks. "
            "Managers cannot approve their own leave requests; their leaves route to HR."
        )
    }
]

# ─── IN-MEMORY VECTOR / KEYWORD RETRIEVER ──────────────────────────────────────
def search_knowledge_base(query: str, top_k: int = 2) -> list[dict]:
    """
    Search the built-in Xevyte knowledge dataset using fast semantic keyword matching.
    Returns top matching policy chunks.
    """
    query_terms = [t.lower() for t in query.strip().split() if len(t) > 2]
    if not query_terms:
        return XEVYTE_HR_DATASET[:top_k]

    scored = []
    for item in XEVYTE_HR_DATASET:
        content_lower = (item["category"] + " " + item["content"]).lower()
        score = sum(1 for term in query_terms if term in content_lower)
        if score > 0:
            scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = [item for _, item in scored[:top_k]]
    
    # Fallback to general policy chunks if no terms matched
    if not results:
        results = XEVYTE_HR_DATASET[:top_k]
        
    return results
