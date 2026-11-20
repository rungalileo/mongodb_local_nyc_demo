"""
Setup Promos for MongoDB Atlas.

Seeds discount offers for the catalog product. Two per product:

  - FALL-SALE (live):    the RIGHT deal — "Fall Into Savings Sale", $200 off all
                         phones, still valid (future end date).
  - QMOBILE   (expired): the STALE deal — "QMobile" carrier promotion, $700 off,
                         expired ~7 days ago.

QMOBILE is DELIBERATELY EXPIRED (``effective_until`` in the past, ``expired``
true). The promo lookup doesn't filter it out, and because the agent's Select
Promotion step is told to offer the *biggest* dollar discount, it reaches for the
expired $700 QMobile deal over the live $200 Fall sale even though the record
says it's expired — the leak the demo catches. With the steer control on, it
turns around and lands on the live FALL-SALE ($200) instead.

The stored dates only matter for anyone browsing the collection: the app
re-derives dates and ``expired`` from ``tier`` on every read (see
``promo_dates_for_tier``), so the demo never drifts as the seed ages.

Run after setup_products.py.
"""

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
from typing import List

from dotenv import load_dotenv

from app.rag.atlas_client import get_atlas_client
from app.models.product import Product
from app.models.promo import Promo, promo_dates_for_tier
from setup_products import PRODUCTS

load_dotenv()


def _build_promos(products: List[Product]) -> List[Promo]:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    promos: List[Promo] = []
    for p in products:
        promos.append(
            Promo(
                _id=f"promo_{p.sku}_fall",
                code="FALL-SALE",
                sku=p.sku,
                description="Fall Into Savings Sale — $200 off all phones, ends soon",
                discount_type="fixed",
                discount_value=200.0,  # the RIGHT deal: $200 off
                currency=p.currency,
                tier="live",  # valid for another 30 days
                **promo_dates_for_tier("live", now),
            )
        )
        promos.append(
            Promo(
                _id=f"promo_{p.sku}_qmobile",
                code="QMOBILE",
                sku=p.sku,
                description="QMobile partner promotion — $700 off with QMobile activation",
                discount_type="fixed",
                discount_value=700.0,  # the WRONG deal: $700 off (expired)
                currency=p.currency,
                tier="qmobile",  # ended 7 days ago
                **promo_dates_for_tier("qmobile", now),
            )
        )
    return promos


PROMOS: List[Promo] = _build_promos(PRODUCTS)


async def clear_promos():
    client = get_atlas_client()
    if not client.client:
        print("❌ No Atlas connection available. Set MONGODB_URI environment variable.")
        return
    try:
        result = client.db.promos.delete_many({})
        print(f"🗑️  Cleared {result.deleted_count} promos")
    except Exception as e:
        print(f"❌ Error clearing promos: {e}")


async def upload_promos():
    client = get_atlas_client()
    if not client.client:
        print("❌ No Atlas connection available. Set MONGODB_URI environment variable.")
        return
    print("🏷️  Uploading promos (FALL-SALE $200 live; QMOBILE $700 expired)...")
    try:
        for promo in PROMOS:
            doc = asdict(promo)
            client.db.promos.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        print(f"✅ Uploaded {len(PROMOS)} promos")
    except Exception as e:
        print(f"❌ Error uploading promos: {e}")


async def main():
    print("🚀 Setting up Promos...")
    print("=" * 50)
    print("\n🔄 Clearing old promo data...")
    await clear_promos()
    print("\n🔄 Uploading promos...")
    await upload_promos()
    print("\n✅ Promo setup complete!")


if __name__ == "__main__":
    asyncio.run(main())
