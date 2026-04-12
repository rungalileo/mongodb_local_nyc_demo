from __future__ import annotations

from typing import Any

from colorama import Fore, Style

from app.rag.atlas_client import embed, get_db


async def records_node(state: dict) -> dict:
    """Records Agent — fetch refund requests, tickets, and orders from MongoDB."""
    print(f"{Fore.GREEN}-> Records Agent: Starting for {state.get('user_id', '?')}{Style.RESET_ALL}")
    user_id = state["user_id"]
    user_query = state["user_query"]
    db = get_db()

    refund_requests = list(db.refund_requests.find({"user_id": user_id}).limit(3))
    for r in refund_requests:
        r["_id"] = str(r["_id"])

    tickets = list(db.tickets.find({"user_id": user_id}).limit(5))
    for t in tickets:
        t["_id"] = str(t["_id"])

    # Vector search for relevant orders
    try:
        vec = embed([user_query])[0]
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "order_index",
                    "path": "embedding",
                    "queryVector": vec,
                    "numCandidates": 10,
                    "limit": 1,
                    "filter": {"user_id": user_id},
                }
            }
        ]
        orders = list(db.orders.aggregate(pipeline))
    except Exception as e:
        print(f"  {Fore.YELLOW}Vector search failed, falling back: {e}{Style.RESET_ALL}")
        orders = list(db.orders.find({"user_id": user_id}).limit(1))

    for o in orders:
        o.pop("embedding", None)
        o["_id"] = str(o["_id"])

    print(
        f"  {Fore.GREEN}Found {len(refund_requests)} requests, "
        f"{len(tickets)} tickets, {len(orders)} orders{Style.RESET_ALL}"
    )
    return {
        "records": {
            "requests": refund_requests,
            "tickets": tickets,
            "orders": orders,
        }
    }
