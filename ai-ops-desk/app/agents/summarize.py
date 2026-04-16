"""Summarization Agent — produce a concise user-facing response from accumulated state.

This agent solves a key observability problem: without it, the LangGraph state dict
is passed through as span input/output at every level, causing Galileo's
action_advancement and action_completion SLMs to see near-identical input/output
(the same state blob with small deltas), scoring close to 0%.

By producing a short natural-language summary as the final output, the trace
input→output delta becomes clear: user question in, resolution answer out.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

SYSTEM_PROMPT = """\
You are a customer service summarizer. Given the internal state of a CRM workflow,
produce a SHORT, friendly reply to the customer (2-4 sentences max).

Include:
- What was done (refund created, ticket escalated, etc.)
- Any relevant IDs (ticket ID, refund request ID)
- Next steps if applicable

Do NOT include internal details like policy IDs, cost breakdowns, or agent names.
Do NOT repeat the customer's original question back to them.
Be direct and helpful."""


async def summarize_node(state: dict, config: RunnableConfig) -> dict:
    """Summarize Agent — distill accumulated state into a user-facing response."""
    action = state.get("action_output", {})
    audit = state.get("audit_output", {})
    records = state.get("records", {})

    # Build a concise context block for the LLM
    parts = [f"Customer query: {state.get('user_query', '?')}"]

    # Action results
    resolution = action.get("resolution", "unknown")
    parts.append(f"Resolution: {resolution}")

    tool_receipts = action.get("tool_receipts", [])
    for r in tool_receipts:
        tool_name = r.get("tool", "unknown").replace("_", " ").title()
        status = r.get("status", 0)
        resp = r.get("response", {})
        # Extract key IDs from tool responses
        ids = {k: v for k, v in resp.items()
               if k.endswith("_id") and k != "user_id" and isinstance(v, str)}
        status_msg = resp.get("status_message", "")
        parts.append(f"Tool: {tool_name} (status {status})"
                     + (f" — {status_msg}" if status_msg else "")
                     + (f" {ids}" if ids else ""))

    # Audit rationale (already human-readable)
    rationale = audit.get("rationale", "")
    if rationale:
        parts.append(f"Audit: {rationale[:300]}")

    # Orders context
    orders = records.get("orders", [])
    if orders:
        o = orders[0]
        parts.append(f"Order: {o.get('product_name', '?')} "
                     f"${o.get('unit_price', 0):.2f} "
                     f"({o.get('status', '?')})")

    context = "\n".join(parts)

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3)
    response = await llm.ainvoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=context),
    ], config=config)

    summary = response.content.strip()
    # Write an AIMessage so SDOT captures it as gen_ai.output.messages
    # on the root GenAI span (invoke_agent CRM Ops Desk).
    return {"summary": summary, "messages": [AIMessage(content=summary)]}
