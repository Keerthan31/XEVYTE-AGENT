"""
Wires the node functions from app.agent.nodes into a LangGraph StateGraph.

    retrieve --> plan --> guardrail --> execute --> respond --> END
       |           |           |
       v           v           v
      END         END         END
   (token       (need more   (need user
   exfil        info from    confirmation
   blocked)     the user)    before write/delete)

Each early exit already set `status` + `reply` in its node, so the router
just needs to short-circuit — no extra logic duplicated here.
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.agent import nodes
from app.agent.state import AgentState


def _after_retrieve(state: AgentState) -> str:
    return "end" if state.get("status") == "error" else "plan"


def _after_plan(state: AgentState) -> str:
    return "end" if state.get("status") == "needs_info" else "guardrail"


def _after_guardrail(state: AgentState) -> str:
    return "end" if state.get("status") == "needs_confirmation" else "execute"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("retrieve", nodes.retrieve_node)
    graph.add_node("plan", nodes.plan_node)
    graph.add_node("guardrail", nodes.guardrail_node)
    graph.add_node("execute", nodes.execute_node)
    graph.add_node("respond", nodes.respond_node)

    graph.set_entry_point("retrieve")
    graph.add_conditional_edges("retrieve", _after_retrieve, {"plan": "plan", "end": END})
    graph.add_conditional_edges("plan", _after_plan, {"guardrail": "guardrail", "end": END})
    graph.add_conditional_edges("guardrail", _after_guardrail, {"execute": "execute", "end": END})
    graph.add_edge("execute", "respond")
    graph.add_edge("respond", END)
    return graph.compile()


_compiled = None


def get_agent_graph():
    global _compiled
    if _compiled is None:
        _compiled = build_graph()
    return _compiled
