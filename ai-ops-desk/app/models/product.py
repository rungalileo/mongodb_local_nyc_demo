"""
Product model for MongoDB Atlas.

Represents an item in the shoppable catalog (distinct from Order, which is a
purchase a customer already made). Used by the promo-inquiry use case where a
customer asks about a discount on an expensive item they're considering.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class Product:
    """Catalog product a customer can shop for."""
    _id: str
    sku: str
    product_name: str
    category: str
    unit_price: float
    currency: str
    description: str
    # Free-text keywords that help match a customer's natural-language query
    # ("the new YPhone") to this catalog entry without needing a vector index.
    keywords: List[str] = field(default_factory=list)
