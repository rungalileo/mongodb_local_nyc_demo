from __future__ import annotations

import random
import time

from langchain_core.tools import tool


@tool
def create_ticket(user_query: str, user_id: str, sentiment: str) -> dict:
    """Create a new CRM support ticket for the customer."""
    time.sleep(random.uniform(0.05, 0.2))
    return {
        "status": 201,
        "ticket_id": f"TKT_{random.randint(10000, 99999)}",
        "user_id": user_id,
        "title": "Customer Request",
        "description": user_query[:280],
        "customer_sentiment": sentiment,
        "comments": {f"{time.strftime('%Y-%m-%d %H:%M:%S')}": "AI Ops Desk creating ticket"},
        "status_message": "Ticket created",
    }


@tool
def update_ticket(ticket_id: str, user_query: str, sentiment: str) -> dict:
    """Update an existing CRM support ticket with new information."""
    time.sleep(random.uniform(0.05, 0.15))
    return {
        "status": 200,
        "ticket_id": ticket_id,
        "customer_sentiment": sentiment,
        "comments": {f"{time.strftime('%Y-%m-%d %H:%M:%S')}": "AI Ops Desk updating ticket"},
        "status_message": "Ticket updated",
    }


@tool
def escalate_ticket(user_query: str, user_id: str, reason: str) -> dict:
    """Escalate a ticket to tier-2 support when the customer is very upset."""
    time.sleep(random.uniform(0.1, 0.3))
    return {
        "status": 200,
        "ticket_id": f"TKT_{random.randint(10000, 99999)}",
        "escalation_level": "tier2",
        "assigned_agent": f"agent_{random.randint(100, 999)}",
        "escalation_reason": reason[:200],
        "status_message": "Ticket escalated to tier 2 support",
    }


@tool
def create_refund_request(
    user_id: str,
    description: str,
    amount: float = 0.0,
    currency: str = "USD",
) -> dict:
    """Create a refund request for the customer."""
    time.sleep(random.uniform(0.05, 0.15))
    return {
        "status": 201,
        "refund_request_id": f"RR_{random.randint(10000, 99999)}",
        "user_id": user_id,
        "amount": amount,
        "currency": currency,
        "description": description[:200],
        "refund_status": "investigation",
        "status_message": "Refund request created",
    }


@tool
def explain_refund_state(user_id: str, user_query: str, refund_requests: list[dict]) -> dict:
    """Explain the current state of existing refund requests to the customer."""
    time.sleep(random.uniform(0.05, 0.1))
    if not refund_requests:
        explanation = f"No refund requests found for user {user_id}."
    else:
        latest = refund_requests[0]
        status = latest.get("status", "unknown")
        amount = latest.get("amount", "unknown")
        currency = latest.get("currency", "USD")
        status_map = {
            "investigation": "Your refund request is currently under investigation.",
            "refund in progress": "Your refund is being processed.",
            "paid": "Your refund has been processed and paid.",
            "closed": "This refund request has been closed.",
            "cancelled": "This refund request has been cancelled.",
        }
        explanation = (
            f"Regarding: {user_query[:100]}... "
            f"Status: {status_map.get(status, f'Status: {status}')}. "
            f"Amount: {currency} {amount}."
        )
    return {"status": 200, "explanation": explanation, "status_message": "Refund state explained"}


@tool
def explain_order_state(user_id: str, user_query: str, orders: list[dict]) -> dict:
    """Explain the current state of the customer's orders."""
    time.sleep(random.uniform(0.05, 0.1))
    if not orders:
        return {
            "status": 200,
            "explanation": f"No orders found for user {user_id}.",
            "status_message": "Order state explained",
        }

    latest = orders[0]
    product_name = latest.get("product_name", "unknown product")
    order_date = str(latest.get("order_date", "unknown date"))
    actual_status = latest.get("status", "unknown")

    # Hallucination injection for user_007
    if user_id == "user_007":
        display_status = "delivered"  # hallucinated
    else:
        display_status = actual_status

    status_map = {
        "delivered": "Your order has been successfully delivered.",
        "shipped": "Your order has been shipped and is on its way.",
        "processing": "Your order is being processed.",
        "returned": "This order has been returned.",
        "cancelled": "This order has been cancelled.",
        "pending": "Your order is pending confirmation.",
    }
    explanation = (
        f"Regarding: {user_query[:100]}... "
        f"Status: {status_map.get(display_status, f'Status: {display_status}')}. "
        f"Product: {product_name}. Order date: {order_date}."
    )
    if user_id == "user_007":
        explanation += f" [WARNING: LLM may have hallucinated — actual DB status: {actual_status}]"
    return {"status": 200, "explanation": explanation, "status_message": "Order state explained"}


# All tools available to the Action agent LLM
CRM_TOOLS = [
    create_ticket,
    update_ticket,
    escalate_ticket,
    create_refund_request,
    explain_refund_state,
    explain_order_state,
]
