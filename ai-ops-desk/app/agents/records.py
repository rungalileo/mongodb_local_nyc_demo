"""
A3: Records Agent - Operational joins and aggregation pipelines
"""

import time
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from colorama import Fore, Style
from app.rag.queries import get_user_refund_requests, get_user_tickets, get_user_order, get_order_by_id
from app.models.order import Order
from app.models.refund_request import RefundRequest
from app.models.ticket import Ticket
from app.models.records_output import RecordsOutput
from app.session_cache import recall_order, remember_order
from app.toggles import ToggleManager
from galileo import log
# Constants for data limits
NUM_REQUESTS_INCLUDED = 3
NUM_TICKETS_INCLUDED = 5
NUM_ORDERS_INCLUDED = 5


class RecordsAgent:
    """A3: Records Agent - Operational data joins and aggregation"""
    
    def __init__(self):
        self.toggles = ToggleManager()
    
    @log(span_type="agent", name="Records Agent - Process")
    async def process(
        self,
        user_query: str,
        user_id: str,
        chat_session_id: Optional[str] = None,
    ) -> RecordsOutput:

        # Goal of this function is to get latest relevant claims and tickets
        try:
            print(f"  {Fore.GREEN}Fetching refund requests...{Style.RESET_ALL}")
            # Get user data
            refund_requests = await get_user_refund_requests(user_id)
            print(f"  {Fore.GREEN}Found {len(refund_requests) if refund_requests else 0} refund requests{Style.RESET_ALL}")

            print(f"  {Fore.GREEN}Fetching support tickets...{Style.RESET_ALL}")
            tickets = await get_user_tickets(user_id)
            print(f"  {Fore.GREEN}Found {len(tickets) if tickets else 0} support tickets{Style.RESET_ALL}")

            # Prefer the order surfaced earlier in this chat session, if any.
            # Vector search on a follow-up like "can you issue a refund?" has
            # no product signal and may return a different order than turn 1,
            # which would break the receipt -> refund narrative.
            cached_order_id = recall_order(chat_session_id)
            print(
                f"  {Fore.GREEN}Session cache lookup: chat_session_id={chat_session_id!r} "
                f"cached_order_id={cached_order_id!r}{Style.RESET_ALL}"
            )
            if cached_order_id:
                print(
                    f"  {Fore.GREEN}Reusing order {cached_order_id} from earlier in chat session{Style.RESET_ALL}"
                )
                orders = await get_order_by_id(user_id, cached_order_id)
                if not orders:
                    # Cached id no longer resolves (rare). Fall back so the
                    # turn still has *some* order context.
                    print(
                        f"  {Fore.YELLOW}Cached order not found; falling back to vector search{Style.RESET_ALL}"
                    )
                    orders = await get_user_order(user_id, user_query)
            else:
                print(f"  {Fore.GREEN}Fetching orders using vector search...{Style.RESET_ALL}")
                orders = await get_user_order(user_id, user_query)
            print(f"  {Fore.GREEN}Found {len(orders) if orders else 0} relevant orders{Style.RESET_ALL}")

            # Cache whatever we resolved so subsequent turns reuse it.
            if orders:
                first = orders[0]
                order_id = first.get("_id") if isinstance(first, dict) else getattr(first, "_id", None)
                remember_order(chat_session_id, order_id)

            # Take most recent N items - no filtering for now
            recent_requests = refund_requests[:NUM_REQUESTS_INCLUDED] if refund_requests else []
            recent_tickets = tickets[:NUM_TICKETS_INCLUDED] if tickets else []
            relevant_orders = orders[:NUM_ORDERS_INCLUDED] if orders else []

            print(f"  {Fore.GREEN}Aggregated: {len(recent_requests)} requests, {len(recent_tickets)} tickets, {len(relevant_orders)} orders{Style.RESET_ALL}")

            return RecordsOutput(
                requests=recent_requests,
                tickets=recent_tickets,
                orders=relevant_orders,
            )
        except Exception as e:
            raise e
