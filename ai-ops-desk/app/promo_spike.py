"""
Time-based discount "spike" schedule for the expired-promo demo.

The demo tells a visual story in the Galileo trace view: for the first stretch
of a run, the agent applies small, ordinary discounts; then the applied
discount amount suddenly spikes. Plotting the ``discount_usd`` span metadata
over time makes the anomaly obvious at a glance.

The schedule is driven by *elapsed time since the traffic run started* so the
"first N minutes normal, then spike" behaviour is reproducible on demand
regardless of the wall-clock time you kick the demo off.

Timeline anchor resolution (first match wins):
  1. ``PROMO_TRAFFIC_START_EPOCH`` env var (unix seconds) — exported by the
     traffic generator so every per-iteration ``main.py`` process shares one
     anchor.
  2. This module's import time — fine for a single long-lived process
     (FastAPI server, a single CLI run).
"""

import os
import random
import time
from datetime import datetime, timedelta
from typing import Any, Dict

# When the process imported this module. Fallback anchor when no traffic run
# has exported PROMO_TRAFFIC_START_EPOCH.
_PROCESS_START_EPOCH = time.time()

# How long the "normal discounts" window lasts before the spike kicks in.
NORMAL_WINDOW_SECONDS = int(os.getenv("PROMO_NORMAL_WINDOW_SECONDS", str(10 * 60)))


def _start_epoch() -> float:
    raw = os.getenv("PROMO_TRAFFIC_START_EPOCH")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return _PROCESS_START_EPOCH


def elapsed_seconds() -> float:
    """Seconds since the traffic run started (never negative)."""
    return max(0.0, time.time() - _start_epoch())


def in_spike_window() -> bool:
    """True once we're past the normal window and discounts should spike."""
    return elapsed_seconds() >= NORMAL_WINDOW_SECONDS


def discount_for_now(product_price: float) -> Dict[str, Any]:
    """Compute the discount to apply right now per the demo spike schedule.

    Returns a dict describing the (deliberately expired) promo the agent is
    about to apply. ``discount_usd`` is the field the demo plots over time.

    - Normal window: a small, plausible "seasonal" discount ($5–$60).
    - Spike window:  an outsized "clearance blowout" (40–65% of list price).

    Both tiers reference a promo whose end date is in the past, matching the
    stale/expired records seeded by ``setup_promos.py``.
    """
    price = max(0.0, float(product_price or 0.0))
    spike = in_spike_window()

    if spike:
        discount_usd = round(min(700.0, price), 2)
        code = "QMOBILE"
        description = "QMobile partner promotion — $700 off with QMobile activation"
        # Seeded as expired ~7 days ago.
        end_date = datetime.utcnow() - timedelta(days=7)
        # Stale record: the expiry flag was last refreshed ~2 months ago.
        last_updated_at = datetime.utcnow() - timedelta(days=60)
        tier = "qmobile"
    else:
        discount_usd = round(min(random.uniform(5.0, 60.0), price), 2)
        code = "SEASONAL-SAVER"
        description = "Seasonal Saver — small seasonal markdown"
        # Seeded as expired ~30 days ago.
        end_date = datetime.utcnow() - timedelta(days=30)
        last_updated_at = datetime.utcnow() - timedelta(days=90)
        tier = "normal"

    return {
        "tier": tier,
        "in_spike": spike,
        "elapsed_seconds": round(elapsed_seconds(), 1),
        "discount_usd": discount_usd,
        "promo_code": code,
        "promo_description": description,
        "promo_end_date": end_date,
        "promo_expired": True,
        "promo_last_updated_at": last_updated_at.isoformat(),
    }
