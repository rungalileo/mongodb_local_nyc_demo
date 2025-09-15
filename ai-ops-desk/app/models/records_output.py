"""
RecordsOutput model for agent outputs

This module defines the RecordsOutput class used by the RecordsAgent.
"""

from typing import List
from pydantic import BaseModel
from app.models.refund_request import RefundRequest
from app.models.ticket import Ticket
from app.models.order import Order


class RecordsOutput(BaseModel):
    """RecordsOutput class for RecordsAgent results"""
    requests: List[RefundRequest]
    tickets: List[Ticket]
    orders: List[Order]
