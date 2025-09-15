"""
RefundRequest model for MongoDB Atlas

This module defines the RefundRequest dataclass used for refund request data.
"""

from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime


@dataclass
class RefundRequest:
    """RefundRequest dataclass for refund request data"""
    _id: str
    user_id: str
    sku: str
    product_name: str
    amount: float
    currency: str
    status: str
    filed_date: datetime
    purchase_date: datetime
    reason: str
    description: str
    related_tickets: List[str]
    order_id: str
    refund_method: str
    expected_refund_date: Optional[datetime]
    actual_refund_date: Optional[datetime]
    processed_by: Optional[str]
    notes: Optional[str]
    category: str
    subcategory: str
    warranty_covered: bool
    return_shipping_required: bool
    return_tracking_number: Optional[str]
    created_at: datetime
    updated_at: datetime
