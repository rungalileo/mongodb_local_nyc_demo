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


PRODUCTS: List[Product] = [
    Product(
        _id="prod_001",
        sku="TV_OLED_85_A9",
        product_name="85-inch OLED 4K Smart TV",
        category="home_entertainment",
        unit_price=2499.99,
        currency="USD",
        description="Flagship 85-inch OLED television with 4K HDR and smart platform.",
        keywords=["tv", "television", "oled", "85-inch", "85", "4k", "smart"],
    ),
    Product(
        _id="prod_002",
        sku="CAM_MIRRORLESS_X9",
        product_name="Pro Mirrorless Camera X9",
        category="photography",
        unit_price=1899.99,
        currency="USD",
        description="Full-frame mirrorless camera body for professional photography.",
        keywords=["camera", "mirrorless", "x9", "photography", "photo"],
    ),
    Product(
        _id="prod_003",
        sku="LAP_ULTRABOOK_PRO16",
        product_name="UltraBook Pro 16 Laptop",
        category="computers",
        unit_price=2199.99,
        currency="USD",
        description="16-inch professional ultrabook with high-performance CPU/GPU.",
        keywords=["laptop", "ultrabook", "notebook", "computer", "pro", "16"],
    ),
    Product(
        _id="prod_004",
        sku="AUD_HOME_THEATER_HT7",
        product_name="Home Theater Surround System HT7",
        category="audio",
        unit_price=1299.99,
        currency="USD",
        description="7.1 channel home theater surround sound system with wireless rears.",
        keywords=["home", "theater", "surround", "speakers", "soundbar", "audio", "ht7"],
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
