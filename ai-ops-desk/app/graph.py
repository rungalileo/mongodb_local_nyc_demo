"""
LangGraph-based multi-agent orchestration for AI Operations Desk

Implements the agent workflow (linear):
Policy → Records → Action → Audit → END
"""

import time
from typing import Dict, Any, List, Optional
from enum import Enum

from langgraph.graph import StateGraph, END
from typing_extensions import Annotated
from galileo import log

from app.agents.policy import PolicyAgent
from app.agents.records import RecordsAgent
from app.agents.action import ActionAgent
from app.agents.audit import AuditAgent
from app.models.policy_output import PolicyOutput
from app.models.records_output import RecordsOutput
from app.models.action_output import ActionOutput
from app.models.audit_output import AuditOutput


class AgentState(dict):
    """State passed between agents in the graph"""
    
    # Input
    user_query: str
    user_id: str
    scenario: str
    
    # Agent outputs
    policy_output: Optional[PolicyOutput] = None
    records_output: Optional[RecordsOutput] = None
    action_output: Optional[ActionOutput] = None
    audit_output: Optional[AuditOutput] = None
    
    # Control flow (minimal)
    status: str = "running"
    error: Optional[str] = None
    
    # Timestamps for handoff latency
    agent_start_times: Dict[str, float] = None
    agent_end_times: Dict[str, float] = None
    
    def __post_init__(self):
        if self.agent_start_times is None:
            self.agent_start_times = {}
        if self.agent_end_times is None:
            self.agent_end_times = {}


def record_agent_timing(state: AgentState, agent_name: str, start: bool = True):
    """Record agent start/end times for handoff latency calculation"""
    current_time = time.time()
    # Ensure timing dicts exist
    if "agent_start_times" not in state or not isinstance(state.get("agent_start_times"), dict):
        state["agent_start_times"] = {}
    if "agent_end_times" not in state or not isinstance(state.get("agent_end_times"), dict):
        state["agent_end_times"] = {}

    if start:
        state["agent_start_times"][agent_name] = current_time
    else:
        state["agent_end_times"][agent_name] = current_time


@log(span_type="workflow", name="Policy Node")
async def policy_node(state: AgentState) -> AgentState:
    """Policy agent node"""
    print(f"🔄 [GRAPH] Entering policy node for user {state.get('user_id', 'unknown')}")
    record_agent_timing(state, "policy", start=True)
    
    try:
        agent = PolicyAgent()
        
        order = None
        if state.get("records_output") and state.get("records_output").orders:
            order = state.get("records_output").orders[0]
        result = await agent.process(user_query=state["user_query"], user_id=state["user_id"], order = order)        
        state["policy_output"] = result
        print(f"✅ [GRAPH] Exiting policy node - success")
    except Exception as e:
        print(f"❌ [GRAPH] Exiting policy node - error: {str(e)}")
        print("Exception: Agent failed at this state: policy")
        state["error"] = f"Policy agent failed: {str(e)}"
        state["status"] = "error"
    
    record_agent_timing(state, "policy", start=False)
    return state


@log(span_type="workflow", name="Records Node")
async def records_node(state: AgentState) -> AgentState:
    """Records agent node"""
    print(f"🔄 [GRAPH] Entering records node for user {state.get('user_id', 'unknown')}")
    record_agent_timing(state, "records", start=True)
    
    try:
        agent = RecordsAgent()
        result = await agent.process(user_query=state["user_query"], user_id=state["user_id"])
        
        state["records_output"] = result
        print(f"✅ [GRAPH] Exiting records node - success")
        
    except Exception as e:
        print(f"❌ [GRAPH] Exiting records node - error: {str(e)}")
        print("Exception: Agent failed at this state: records")
        state["error"] = f"Records agent failed: {str(e)}"
        state["status"] = "error"
    
    record_agent_timing(state, "records", start=False)
    return state


@log(span_type="workflow", name="Action Node")
async def action_node(state: AgentState) -> AgentState:
    """Action agent node"""
    print(f"🔄 [GRAPH] Entering action node for user {state.get('user_id', 'unknown')}")
    record_agent_timing(state, "action", start=True)
    
    try:
        agent = ActionAgent()
        result = await agent.process(state["user_id"], state["user_query"], state.get("policy_output"), state.get("records_output"))
        
        state["action_output"] = result
        print(f"✅ [GRAPH] Exiting action node - success")
        
    except Exception as e:
        print(f"❌ [GRAPH] Exiting action node - error: {str(e)}")
        print("Exception: Agent failed at this state: action")
        state["error"] = f"Action agent failed: {str(e)}"
        state["status"] = "error"
    
    record_agent_timing(state, "action", start=False)
    return state


@log(span_type="workflow", name="Audit Node")
async def audit_node(state: AgentState) -> AgentState:
    """Audit agent node"""
    print(f"🔄 [GRAPH] Entering audit node for user {state.get('user_id', 'unknown')}")
    record_agent_timing(state, "audit", start=True)
    
    try:
        agent = AuditAgent()
        result = await agent.process(user_query=state["user_query"], user_id=state["user_id"], policy_output=state.get("policy_output"), records_output=state.get("records_output"), action_output=state.get("action_output"))
        
        state["audit_output"] = result
        state["status"] = "completed"
        
        # Extract final resolution from action output
        if state.get("action_output"):
            state["resolution"] = state["action_output"].resolution
        
        print(f"✅ [GRAPH] Exiting audit node - success (workflow completed)")
        
    except Exception as e:
        print(f"❌ [GRAPH] Exiting audit node - error: {str(e)}")
        print("Exception: Agent failed at this state: audit")
        state["error"] = f"Audit agent failed: {str(e)}"
        state["status"] = "error"
    
    record_agent_timing(state, "audit", start=False)
    return state


'''
policy → records → action → audit → END
'''
async def create_ops_desk_graph():
    """Create and configure the operations desk agent graph"""
    
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("records", records_node)
    workflow.add_node("policy", policy_node)
    workflow.add_node("action", action_node)
    workflow.add_node("audit", audit_node)
    
    # Set entry point
    workflow.set_entry_point("records")
    
    # Add linear edges
    workflow.add_edge("records", "policy")
    workflow.add_edge("policy", "action")
    workflow.add_edge("action", "audit")
    workflow.add_edge("audit", END)
    
    return workflow.compile()
