"""
A3: Records Agent - Operational joins and aggregation pipelines
"""

import time
from typing import Dict, Any, List
from pydantic import BaseModel
from app.rag.queries import get_user_refund_requests, get_user_tickets, get_user_order
from app.models.order import Order
from app.models.refund_request import RefundRequest
from app.models.ticket import Ticket
from app.models.records_output import RecordsOutput
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
    
    @log(span_type="agent", name="Records Agent Process")
    async def process(self, user_query: str, user_id: str) -> RecordsOutput:
        
        # Goal of this function is to get latest relevant claims and tickets
        try:
            # Get user data
            refund_requests = await get_user_refund_requests(user_id)
            tickets = await get_user_tickets(user_id)
            orders = await get_user_order(user_id, user_query)
            
            # Take most recent N items - no filtering for now
            recent_requests = refund_requests[:NUM_REQUESTS_INCLUDED] if refund_requests else []
            recent_tickets = tickets[:NUM_TICKETS_INCLUDED] if tickets else []
            relevant_orders = orders[:NUM_ORDERS_INCLUDED] if orders else []
            return RecordsOutput(
                requests=recent_requests,
                tickets=recent_tickets,
                orders=relevant_orders,
            )
        except Exception as e:
            raise e
