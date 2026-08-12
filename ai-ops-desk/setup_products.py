"""
Setup Products (shoppable catalog) for MongoDB Atlas.

Seeds a small catalog of expensive items used by the expired-promo use case.
Unlike orders, these are things the customer is *considering buying*, so the
agent can be asked "is there a discount on X?".

No embeddings/vector index required — the promo tools resolve a product by
keyword match (see AtlasClient.find_product), which keeps the demo working on
a fresh cluster without extra index setup.
"""

import asyncio
from dataclasses import asdict
from typing import List

from dotenv import load_dotenv

from app.rag.atlas_client import get_atlas_client
from app.models.product import Product

load_dotenv()


# Single product for the simplified promo demo: one flagship phone at a round
# $1,000 list price. The whole leak story turns on one item, so there's exactly
# one thing in the catalog.
PRODUCTS: List[Product] = [
    Product(
        _id="prod_001",
        sku="PHONE_IPHONE16_PROMAX",
        product_name="iPhone 16 Pro Max",
        category="smartphones",
        unit_price=1000.00,
        currency="USD",
        description="Apple flagship smartphone with the A18 Pro chip, titanium design, and Pro camera system.",
        keywords=["iphone", "iphone 16", "16 pro max", "pro max", "phone", "smartphone", "apple", "16", "ios"],
    ),
]


async def clear_products():
    client = get_atlas_client()
    if not client.client:
        print("❌ No Atlas connection available. Set MONGODB_URI environment variable.")
        return
    try:
        result = client.db.products.delete_many({})
        print(f"🗑️  Cleared {result.deleted_count} products")
    except Exception as e:
        print(f"❌ Error clearing products: {e}")


async def upload_products():
    client = get_atlas_client()
    if not client.client:
        print("❌ No Atlas connection available. Set MONGODB_URI environment variable.")
        return
    print("🛍️  Uploading products...")
    try:
        for product in PRODUCTS:
            doc = asdict(product)
            client.db.products.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        print(f"✅ Uploaded {len(PRODUCTS)} products")
    except Exception as e:
        print(f"❌ Error uploading products: {e}")


async def main():
    print("🚀 Setting up Products...")
    print("=" * 50)
    print("\n🔄 Clearing old product data...")
    await clear_products()
    print("\n🔄 Uploading products...")
    await upload_products()
    print("\n✅ Product setup complete!")


if __name__ == "__main__":
    asyncio.run(main())
