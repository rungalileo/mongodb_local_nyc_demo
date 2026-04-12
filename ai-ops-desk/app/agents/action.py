from __future__ import annotations

import json
from typing import Any

from colorama import Fore, Style
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode

from app.models.action_output import ActionOutput, ToolReceipt
from app.tools.crm_tools import CRM_TOOLS

MAX_TOOL_ROUNDS = 3


async def action_node(state: dict) -> dict:
    """Action Agent — LLM decides which CRM tools to call and executes them.

    Runs the full tool-calling loop inside a single graph node so that
    the SDOT instrumentor emits exactly one ``invoke_agent`` span for the
    Action Agent (matching the original CRM app's telemetry shape).
    """
    print(f"{Fore.YELLOW}-> Action Agent: Starting{Style.RESET_ALL}")
    records = state.get("records", {})
    policies = state.get("policies", [])

    # Build context summary for the LLM
    context_parts = []
    requests = records.get("requests", [])
    tickets = records.get("tickets", [])
    orders = records.get("orders", [])

    if requests:
        context_parts.append(
            f"Existing refund requests ({len(requests)}):\n"
            + json.dumps(requests[:2], indent=2, default=str)
        )
    if tickets:
        context_parts.append(
            f"Existing support tickets ({len(tickets)}):\n"
            + json.dumps(tickets[:2], indent=2, default=str)
        )
    if orders:
        context_parts.append(
            f"Customer orders ({len(orders)}):\n"
            + json.dumps(orders[:2], indent=2, default=str)
        )
    if policies:
        policy_summary = [
            {"version": p.get("version"), "region": p.get("region"),
             "refund_window_days": p.get("refund_window_days"),
             "effective_until": str(p.get("effective_until", "current"))}
            for p in policies[:3]
        ]
        context_parts.append(f"Applicable policies:\n{json.dumps(policy_summary, indent=2)}")

    context_block = "\n\n".join(context_parts) if context_parts else "No prior records found."

    system_prompt = f"""You are the Action Agent in a CRM Operations Desk.
Your job is to decide what actions to take for a customer request and execute
the appropriate tools.

Customer ID: {state['user_id']}

== Context from Records & Policy agents ==
{context_block}

== Instructions ==
1. Analyse the customer's sentiment (negative/neutral/positive).
2. If the customer is angry or very negative, escalate the ticket.
3. If the customer wants a refund or return, create a refund request AND
   explain the refund state.
4. If the customer is asking about an order, explain the order state.
5. Always create or update a support ticket.
6. Pass accurate data to the tools — use the customer's actual order amounts,
   ticket IDs, and refund request data from the context above.
7. Call ALL relevant tools in a SINGLE response. Do NOT repeat tool calls.
8. Once you receive tool results, summarise the outcome for the customer.
   Do NOT call the same tool again."""

    user_msg = state["user_query"]

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)
    llm_with_tools = llm.bind_tools(CRM_TOOLS)
    tool_node = ToolNode(CRM_TOOLS)

    messages: list = [SystemMessage(content=system_prompt), HumanMessage(content=user_msg)]

    # Tool-calling loop (capped at MAX_TOOL_ROUNDS)
    for round_num in range(MAX_TOOL_ROUNDS):
        response = await llm_with_tools.ainvoke(messages)
        messages.append(response)

        if not response.tool_calls:
            break

        tool_names = [tc["name"] for tc in response.tool_calls]
        print(f"  {Fore.YELLOW}LLM chose tools: {', '.join(tool_names)}{Style.RESET_ALL}")

        # Execute tools via ToolNode
        result = await tool_node.ainvoke({"messages": messages})
        messages.extend(result["messages"])

    # Collect tool results into ActionOutput
    tool_receipts: list[dict] = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            try:
                content = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
            except (json.JSONDecodeError, TypeError):
                content = {"raw": str(msg.content)}
            tool_receipts.append(
                ToolReceipt(
                    tool=msg.name or "unknown",
                    status=content.get("status", 200) if isinstance(content, dict) else 200,
                    latency_ms=0,
                    response=content if isinstance(content, dict) else {"raw": str(content)},
                ).model_dump()
            )

    # Determine resolution
    if not tool_receipts:
        resolution = "no_action_required"
    else:
        successful = [r["tool"] for r in tool_receipts if 200 <= r["status"] < 300]
        if "create_refund_request" in successful:
            resolution = "refund_request_created"
        elif "escalate_ticket" in successful:
            resolution = "ticket_escalated"
        elif "update_ticket" in successful:
            resolution = "ticket_updated"
        elif "create_ticket" in successful:
            resolution = "ticket_created"
        elif "explain_refund_state" in successful:
            resolution = "refund_state_explained"
        else:
            resolution = "action_failed"

    tool_costs = {
        "create_ticket": 0.0015,
        "update_ticket": 0.001,
        "escalate_ticket": 0.003,
        "create_refund_request": 0.0015,
        "explain_refund_state": 0.0005,
        "explain_order_state": 0.0005,
    }
    total_cost = 0.002  # base cost for LLM calls
    for r in tool_receipts:
        total_cost += tool_costs.get(r["tool"], 0.001)

    action_output = ActionOutput(
        resolution=resolution,
        tool_receipts=[ToolReceipt(**r) for r in tool_receipts],
        cost_token_usd=total_cost,
    )
    print(f"  {Fore.YELLOW}Resolution: {resolution} ({len(tool_receipts)} tools){Style.RESET_ALL}")
    return {"action_output": action_output.model_dump()}
