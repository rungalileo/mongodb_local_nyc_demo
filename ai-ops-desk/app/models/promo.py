"""
Promo model for MongoDB Atlas.

A time-boxed discount for a product (or SKU). The demo deliberately seeds
promos whose ``effective_until`` is already in the past. The agent's promo
lookup reads a stale cache and surfaces these expired promos as if they were
still valid — the failure mode this use case is built to catch in Galileo.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Promo:
    """A discount offer scoped to a single product SKU."""
    _id: str
    code: str
    sku: str
    description: str
    # "percent" -> discount_value is a fraction (0.15 == 15% off).
    # "fixed"   -> discount_value is an absolute amount in `currency`.
    discount_type: str
    discount_value: float
    currency: str
    effective_from: datetime
    # None means open-ended (still active). A past datetime means EXPIRED.
    effective_until: Optional[datetime] = None
    # "normal" seasonal promo vs "spike" clearance blowout. Drives the demo's
    # time-based discount-magnitude pattern (see app/promo_spike.py).
    tier: str = "normal"

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.utcnow()
        return self.effective_until is not None and self.effective_until < now
