"""
Order model for MongoDB Atlas

This module defines the Order dataclass used for e-commerce order data.
"""

from dataclasses import dataclass
from typing import Dict
from datetime import datetime


@dataclass
class Order:
    """Order dataclass for e-commerce orders"""
    _id: str
    user_id: str
    sku: str
    product_name: str
    quantity: int
    unit_price: float
    currency: str
    order_date: datetime
    shipping_address: Dict[str, str]
    status: str
