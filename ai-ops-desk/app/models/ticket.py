"""
Ticket model for MongoDB Atlas

This module defines the Ticket dataclass used for support ticket data.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
from datetime import datetime


@dataclass
class Ticket:
    """Ticket dataclass for support ticket data"""
    _id: str
    ticket_number: str
    user_id: str
    title: str
    description: str
    status: str
    priority: str
    assignee: str
    assignee_name: str
    created_date: datetime
    updated_date: datetime
    due_date: datetime
    channel: str
    customer_sentiment: str
    category: str
    subcategory: str
    related_refund_requests: List[str]
    order_id: str
    tags: List[str]
    comments: Dict[str, str]
    resolution: str
    resolution_date: datetime
    customer_satisfaction: int
    escalated: bool
    escalated_to: Optional[str]
    escalated_date: Optional[datetime]
    time_spent_minutes: int
    attachments: List[str]
    internal_notes: str
    created_at: datetime
    updated_at: datetime
