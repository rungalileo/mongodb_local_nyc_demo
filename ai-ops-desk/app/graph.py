"""CRM Ops Desk graph definition — Records → Policy → Action → Audit."""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.messages import AnyMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from app.agents.records import records_node
from app.agents.policy import policy_node
from app.agents.action import action_node
from app.agents.audit import audit_node
from app.agents.summarize import summarize_node


class CRMState(TypedDict, total=False):
    """State passed between agents in the graph."""
    # Input
    user_query: str
    user_id: str
    scenario: str
    # Agent outputs — stored as serialisable dicts / lists
    records: dict[str, Any]        # {requests, tickets, orders}
    policies: list[dict[str, Any]]
    action_output: dict[str, Any]  # ActionOutput.model_dump()
    audit_output: dict[str, Any]   # AuditOutput.model_dump()
    # Summarization
    summary: str                     # user-facing natural-language response
    # LangChain messages — used by SDOT to capture input/output on the
    # root GenAI span.  The first HumanMessage becomes gen_ai.input.messages
    # and the last AIMessage becomes gen_ai.output.messages.
    messages: Annotated[list[AnyMessage], add_messages]
    # Control
    status: str
    error: str


def build_graph():
    """Build and compile the CRM Ops Desk LangGraph."""
    workflow = StateGraph(CRMState)

    workflow.add_node("records", records_node)
    workflow.add_node("policy", policy_node)
    workflow.add_node("action", action_node)
    workflow.add_node("audit", audit_node)
    workflow.add_node("summarize", summarize_node)

    # Linear flow: records -> policy -> action -> audit -> summarize -> END
    workflow.set_entry_point("records")
    workflow.add_edge("records", "policy")
    workflow.add_edge("policy", "action")
    workflow.add_edge("action", "audit")
    workflow.add_edge("audit", "summarize")
    workflow.add_edge("summarize", END)

    return workflow.compile(name="CRM Ops Desk")
