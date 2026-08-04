"""
RAG Tool Module for Xevyte HRMS AI Agent.
Provides semantic policy retrieval tool for company rules, SLAs, and guidelines.
"""

import time
from langchain_core.tools import tool
from knowledge_base import search_knowledge_base
from tools import format_tool_response

@tool
def search_company_policies(query: str) -> str:
    """
    Search Xevyte HR company policies, leave rules, ticket SLAs, attendance rules,
    and grievance guidelines. Use this tool whenever a user asks about company policy,
    rules, SLAs, or how a feature/process works.
    
    Args:
        query: Specific policy question or topic (e.g., "leave cancellation policy", "ticket SLA", "grievance anonymity")
    """
    t0 = time.time()
    if not query or not query.strip():
        return format_tool_response(
            success=False,
            message="Policy query cannot be empty.",
            tool_name="search_company_policies",
            exec_time_ms=(time.time() - t0) * 1000,
            error_code="VALIDATION_ERROR",
        )

    results = search_knowledge_base(query, top_k=3)
    exec_time = (time.time() - t0) * 1000

    return format_tool_response(
        success=True,
        message=f"Retrieved {len(results)} relevant policy rules for query '{query}'.",
        data={"query": query, "policy_chunks": results},
        tool_name="search_company_policies",
        exec_time_ms=exec_time,
    )
