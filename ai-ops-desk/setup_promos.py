"""
Setup Promos for MongoDB Atlas.

Seeds discount offers for the catalog products. Three per product:

  - MEMBER-SAVE       (live):   small member discount, still valid (future end
                                date). Establishes the "normal, correct" case
                                so the demo isn't ALL expired promos.
  - SPRING-SAVER      (normal): small seasonal markdown, expired ~30 days ago
  - CLEARANCE-BLOWOUT (spike):  outsized clearance %, expired ~7 days ago

The two SPRING-SAVER / CLEARANCE-BLOWOUT promos are DELIBERATELY EXPIRED
(``effective_until`` in the past): this is the stale data the agent's promo
lookup surfaces as if it were still live. Because the agent proposes the
*biggest* dollar discount, it reaches for the expired 55% clearance over the
live member deal — the leak the demo catches.

The two expired tiers match app/promo_spike.py.

Run after setup_products.py.
"""

import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import List

from dotenv import load_dotenv

from app.rag.atlas_client import get_atlas_client
from app.models.product import Product
from app.models.promo import Promo
from setup_products import PRODUCTS

load_dotenv()


def _build_promos(products: List[Product]) -> List[Promo]:
    now = datetime.utcnow()
    promos: List[Promo] = []
    for p in products:
        promos.append(
            Promo(
                _id=f"promo_{p.sku}_member",
                code="MEMBER-SAVE",
                sku=p.sku,
                description="Member Save — small loyalty discount, currently live",
                discount_type="fixed",
                discount_value=25.0,
                currency=p.currency,
                effective_from=now - timedelta(days=10),
                effective_until=now + timedelta(days=30),  # LIVE (valid)
                tier="live",
            )
        )
        promos.append(
            Promo(
                _id=f"promo_{p.sku}_spring",
                code="SPRING-SAVER",
                sku=p.sku,
                description="Spring Saver — small seasonal markdown",
                discount_type="fixed",
                discount_value=40.0,
                currency=p.currency,
                effective_from=now - timedelta(days=120),
                effective_until=now - timedelta(days=30),  # EXPIRED
                tier="normal",
            )
        )
        promos.append(
            Promo(
                _id=f"promo_{p.sku}_clearance",
                code="CLEARANCE-BLOWOUT",
                sku=p.sku,
                description="Clearance blowout — up to 65% off flagship electronics",
                discount_type="percent",
                discount_value=0.55,
                currency=p.currency,
                effective_from=now - timedelta(days=45),
                effective_until=now - timedelta(days=7),  # EXPIRED
                tier="spike",
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
    print("🏷️  Uploading promos (one live per product; SPRING/CLEARANCE expired)...")
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
