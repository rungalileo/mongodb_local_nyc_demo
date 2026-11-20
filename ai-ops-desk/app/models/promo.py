"""
Promo model for MongoDB Atlas.

A time-boxed discount for a product (or SKU). The demo keeps an expired promo
next to the live one. The data is accurate — the expired promo is flagged as
expired — but the promo lookup doesn't filter it out, so the agent's LLM step
can still pick it. That pick is the failure this use case is built to catch in
Galileo.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional


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
    expired: bool = False
    last_updated_at: Optional[datetime] = None

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.utcnow()
        return self.effective_until is not None and self.effective_until < now


# (effective_from, effective_until, last_updated_at) offsets from "now" per tier.
# Promo dates are always derived from these at read time so the live promo is
# always valid and every other tier always just expired, whatever day the demo
# runs and however long ago the collection was seeded.
_LIVE_WINDOW = (timedelta(days=-10), timedelta(days=30), timedelta(days=-1))
_EXPIRED_WINDOW = (timedelta(days=-45), timedelta(days=-7), timedelta(days=-60))


def promo_dates_for_tier(tier: Optional[str], now: datetime) -> Dict[str, Any]:
    """Date fields + ``expired`` flag for a promo of ``tier``, relative to ``now``."""
    start, end, updated = _LIVE_WINDOW if str(tier or "").lower() == "live" else _EXPIRED_WINDOW
    effective_until = now + end
    return {
        "effective_from": now + start,
        "effective_until": effective_until,
        "last_updated_at": now + updated,
        "expired": effective_until < now,
    }
