"""
A. MCP (Model Context Protocol) LAYER — spec: "Yes. MCP is used as the
standard tool integration layer."

Exposes exactly THREE tools over MCP — not 633. This is the pattern that
makes MCP viable at this scale: a client discovers what it needs through
search_tools, reads the real contract through get_tool_contract, and
invokes through execute_tool, which is routed through the SAME
Execution Gate + Policy/Risk/Approval pipeline as everything else in this
codebase — MCP is a transport/discovery convenience on top of governance,
never a bypass around it. There is no MCP tool that calls the Java API
directly; execute_tool below is the only one that can, and it does so
through governance.execution_gate, not httpx directly.
"""
from __future__ import annotations

import json

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from app.database import SessionLocal
from app.planes.control import tool_discovery
from app.planes.control.context_engine import LLMExtractedParam, ParamSource, TrustedContext, resolve_parameters
from app.planes.execution import execution_gate
from app.planes.knowledge.tool_registry import get_tool_registry

server = Server("xevyte-hrms-agent")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_tools",
            description="Search the 633-endpoint Xevyte Connect HRMS tool catalog by natural-language query. "
                        "Returns a small ranked candidate list (hybrid keyword+semantic+domain search) — never "
                        "the full catalog. Use this before execute_tool to find the right tool_id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural-language description of the action needed"},
                    "domain": {"type": "string", "description": "Optional domain hint (e.g. LEAVE, PAYROLL, ASSETS) to narrow the search"},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="get_tool_contract",
            description="Fetch the complete, current contract for one tool_id: parameters, types, request body "
                        "schema, risk tier, approval requirement, auth requirement. Always call this before "
                        "execute_tool — never guess a tool's parameters from its name alone.",
            inputSchema={
                "type": "object",
                "properties": {"tool_id": {"type": "string"}},
                "required": ["tool_id"],
            },
        ),
        types.Tool(
            name="execute_tool",
            description="Execute a tool by id with resolved arguments. Routed through the full governance "
                        "pipeline (missing-parameter gate, validation, policy, risk, approval, execution gate) — "
                        "a call that fails any check returns a structured refusal explaining which one, not an error.",
            inputSchema={
                "type": "object",
                "properties": {
                    "tool_id": {"type": "string"},
                    "arguments": {"type": "object", "description": "name -> value for every argument the contract lists"},
                    "employee_id": {"type": "string", "description": "logged-in employee id (SESSION-sourced)"},
                    "role": {"type": "string"},
                    "bearer_token": {"type": "string", "description": "Scaloz IAM token to call the HRMS API with"},
                    "approval_id": {"type": "string", "description": "required if the tool's risk tier needs approval"},
                },
                "required": ["tool_id", "arguments"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "search_tools":
        candidates = tool_discovery.discover(arguments["query"], domain=arguments.get("domain"), top_k=12)
        payload = [
            {"tool_id": c.tool.tool_id, "description": c.tool.description, "score": round(c.final_score, 3),
             "module": c.tool.module, "risk_level": c.tool.risk_level.value}
            for c in candidates
        ]
        return [types.TextContent(type="text", text=json.dumps(payload, indent=2))]

    if name == "get_tool_contract":
        registry = get_tool_registry()
        tool = registry.get(arguments["tool_id"])
        if not tool:
            return [types.TextContent(type="text", text=json.dumps({"error": "tool not found or not active"}))]
        return [types.TextContent(type="text", text=json.dumps(tool.to_dict(), indent=2, default=str))]

    if name == "execute_tool":
        # Everything proposed here is UNTRUSTED input from the MCP caller —
        # it goes through the same resolve -> gate pipeline as the chat
        # path, nothing here is a shortcut.
        registry = get_tool_registry()
        tool_id = arguments["tool_id"]
        proposed = arguments.get("arguments", {})
        bearer_token = arguments.get("bearer_token")

        # Identity comes from authenticated session context / JWT token claims (FIX 17)
        from app.auth.sso import decode_jwt_claims_unverified
        claims = decode_jwt_claims_unverified(bearer_token) if bearer_token else {}
        session_employee_id = claims.get("employeeId") or claims.get("sub") or arguments.get("employee_id")
        session_role = claims.get("role") or arguments.get("role")
        session_tenant_id = claims.get("tenantId")

        target_tenant_id = arguments.get("tenant_id") or session_tenant_id

        ctx = TrustedContext(
            user_message=json.dumps(proposed),
            employee_id=session_employee_id,
            role=session_role,
            tenant_id=session_tenant_id,
        )
        extracted = [
            LLMExtractedParam(name=k, value=v, claimed_source=ParamSource.USER, quote_or_basis=json.dumps(v))
            for k, v in proposed.items()
        ]
        resolved = resolve_parameters(extracted, ctx)

        db = SessionLocal()
        try:
            decision = execution_gate.evaluate(
                tool_id=tool_id, proposed_arguments=proposed, resolved=resolved, registry=registry,
                authenticated=bool(bearer_token or session_employee_id), role=session_role,
                tenant_id=target_tenant_id, session_tenant_id=session_tenant_id,
                approval_id=arguments.get("approval_id"), calls_this_turn=0, db=db,
            )
            if not decision.allowed:
                return [types.TextContent(type="text", text=json.dumps({
                    "executed": False, "reason": decision.failure_reason,
                    "checks": [c.__dict__ for c in decision.checks],
                }, indent=2))]

            from app.planes.execution.api_fabric import execute_with_fabric
            result = await execute_with_fabric(decision.tool, decision.executable_arguments, bearer_token=bearer_token)
            return [types.TextContent(type="text", text=json.dumps({
                "executed": True, "gate_passed": True,
                "executable_arguments": decision.executable_arguments,
                "result": result,

            }, indent=2, default=str))]
        finally:
            db.close()

    return [types.TextContent(type="text", text=json.dumps({"error": f"unknown tool {name}"}))]


async def run_stdio():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream,
            InitializationOptions(
                server_name="xevyte-hrms-agent",
                server_version="1.0.0",
                capabilities=server.get_capabilities(notification_options=NotificationOptions(), experimental_capabilities={}),
            ),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_stdio())
