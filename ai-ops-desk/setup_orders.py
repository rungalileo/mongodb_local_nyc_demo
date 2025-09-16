"""
Setup Orders for MongoDB Atlas

This script creates realistic e-commerce orders that link to users, tickets,
and refund requests.
"""

import asyncio
from dataclasses import asdict
from typing import List
from datetime import datetime
from dotenv import load_dotenv
from app.rag.atlas_client import get_atlas_client
from app.models.order import Order
from app.llm.client import openai_client


# Load environment variables from .env file
load_dotenv()


async def generate_embeddings_for_orders(orders: List[Order]) -> List[dict]:
    """Generate embeddings for order documents"""
    print("🔮 Generating embeddings for orders...")
    
    embeddings = []
    for order in orders:
        # Create a searchable text representation of the order
        order_text = f"{order.product_name} {order.sku} {order.status} {order.shipping_address.get('city', '')} {order.shipping_address.get('country', '')}"
        
        try:
            # Generate embedding
            embedding = await openai_client.client.embed([order_text])
            order_dict = asdict(order)
            order_dict["embedding"] = embedding[0].tolist()
            embeddings.append(order_dict)
        except Exception as e:
            print(f"❌ Error generating embedding for order {order._id}: {e}")
            # Fallback: add order without embedding
            order_dict = asdict(order)
            order_dict["embedding"] = []
            embeddings.append(order_dict)
    
    return embeddings


async def clear_orders():
    """Clear all order documents from Atlas"""
    client = get_atlas_client()

    if not client.client:
        print("❌ No Atlas connection available. Set MONGODB_URI environment variable.")
        return

    try:
        result = client.db.orders.delete_many({})
        print(f"🗑️  Cleared {result.deleted_count} orders")
    except Exception as e:
        print(f"❌ Error clearing orders: {e}")


async def upload_orders():
    """Upload sample order documents to Atlas"""
    client = get_atlas_client()

    if not client.client:
        print("❌ No Atlas connection available. Set MONGODB_URI environment variable.")
        return

    print("🧾 Uploading orders...")

    orders: List[Order] = [
        # User 1 - kept electric toothbrush, earbuds
        Order(
            _id="order_001",
            user_id="user_001",
            sku="ELEC_TOOTHBRUSH_001",
            product_name="Electric Toothbrush Pro",
            quantity=1,
            unit_price=89.99,
            currency="USD",
            order_date=datetime(2025, 8, 1),
            shipping_address={"city": "New York", "country": "US"},
            status="delivered",
        ),
        Order(
            _id="order_002",
            user_id="user_001",
            sku="ELEC_EARBUDS_001",
            product_name="Wireless Earbuds",
            quantity=1,
            unit_price=129.99,
            currency="USD",
            order_date=datetime(2024, 8, 5),
            shipping_address={"city": "New York", "country": "US"},
            status="delivered",
        ),
        # User 2 - returned all items (has tickets and refund requests)
        Order(
            _id="order_003",
            user_id="user_002",
            sku="ELEC_WASHER_001",
            product_name="Smart Washing Machine",
            quantity=1,
            unit_price=899.99,
            currency="USD",
            order_date=datetime(2024, 7, 15),
            shipping_address={"city": "Los Angeles", "country": "US"},
            status="returned",
        ),
        Order(
            _id="order_004",
            user_id="user_002",
            sku="ELEC_DRILL_001",
            product_name="Cordless Drill Set",
            quantity=1,
            unit_price=199.99,
            currency="USD",
            order_date=datetime(2024, 8, 10),
            shipping_address={"city": "Los Angeles", "country": "US"},
            status="returned",
        ),
        Order(
            _id="order_005",
            user_id="user_002",
            sku="ELEC_DRYER_002",
            product_name="Smart Dryer",
            quantity=1,
            unit_price=200.00,
            currency="USD",
            order_date=datetime(2024, 9, 10),
            shipping_address={"city": "London", "country": "UK"},
            status="returned",
        ),
        Order(
            _id="order_006",
            user_id="user_002",
            sku="ELEC_TABLET_001",
            product_name="10-inch Android Tablet",
            quantity=1,
            unit_price=299.99,
            currency="USD",
            order_date=datetime(2024, 10, 5),
            shipping_address={"city": "Los Angeles", "country": "US"},
            status="delivered",
        ),
        # User 3 - Various electronics purchases
        Order(
            _id="order_007",
            user_id="user_003",
            sku="ELEC_LAPTOP_001",
            product_name="Gaming Laptop Pro",
            quantity=1,
            unit_price=1299.99,
            currency="USD",
            order_date=datetime(2024, 6, 20),
            shipping_address={"city": "Chicago", "country": "US"},
            status="delivered",
        ),
        Order(
            _id="order_008",
            user_id="user_003",
            sku="ELEC_MOUSE_001",
            product_name="Wireless Gaming Mouse",
            quantity=2,
            unit_price=79.99,
            currency="USD",
            order_date=datetime(2024, 7, 5),
            shipping_address={"city": "Chicago", "country": "US"},
            status="delivered",
        ),
        Order(
            _id="order_009",
            user_id="user_003",
            sku="ELEC_KEYBOARD_001",
            product_name="Mechanical Keyboard RGB",
            quantity=1,
            unit_price=149.99,
            currency="USD",
            order_date=datetime(2024, 8, 15),
            shipping_address={"city": "Chicago", "country": "US"},
            status="delivered",
        ),
        # User 4 - Home appliances and gadgets
        Order(
            _id="order_010",
            user_id="user_004",
            sku="ELEC_VACUUM_001",
            product_name="Robot Vacuum Cleaner",
            quantity=1,
            unit_price=399.99,
            currency="USD",
            order_date=datetime(2024, 5, 10),
            shipping_address={"city": "Miami", "country": "US"},
            status="delivered",
        ),
        Order(
            _id="order_011",
            user_id="user_004",
            sku="ELEC_AIRPURIFIER_001",
            product_name="Smart Air Purifier",
            quantity=1,
            unit_price=299.99,
            currency="USD",
            order_date=datetime(2024, 6, 25),
            shipping_address={"city": "Miami", "country": "US"},
            status="delivered",
        ),
        Order(
            _id="order_012",
            user_id="user_004",
            sku="ELEC_SMARTWATCH_001",
            product_name="Fitness Smartwatch",
            quantity=1,
            unit_price=249.99,
            currency="USD",
            order_date=datetime(2024, 9, 1),
            shipping_address={"city": "Miami", "country": "US"},
            status="delivered",
        ),
        # User 5 - Kitchen electronics
        Order(
            _id="order_013",
            user_id="user_005",
            sku="ELEC_COFFEEMAKER_001",
            product_name="Smart Coffee Maker",
            quantity=1,
            unit_price=199.99,
            currency="USD",
            order_date=datetime(2024, 4, 15),
            shipping_address={"city": "Seattle", "country": "US"},
            status="delivered",
        ),
        Order(
            _id="order_014",
            user_id="user_005",
            sku="ELEC_BLENDER_001",
            product_name="High-Speed Blender",
            quantity=1,
            unit_price=179.99,
            currency="USD",
            order_date=datetime(2024, 5, 30),
            shipping_address={"city": "Seattle", "country": "US"},
            status="delivered",
        ),
        Order(
            _id="order_015",
            user_id="user_005",
            sku="ELEC_TOASTER_001",
            product_name="4-Slice Toaster Oven",
            quantity=1,
            unit_price=89.99,
            currency="USD",
            order_date=datetime(2024, 7, 20),
            shipping_address={"city": "Seattle", "country": "US"},
            status="delivered",
        ),
        # User 6 - Entertainment and audio equipment
        Order(
            _id="order_016",
            user_id="user_006",
            sku="ELEC_TV_001",
            product_name="55-inch Smart TV",
            quantity=1,
            unit_price=799.99,
            currency="USD",
            order_date=datetime(2024, 3, 10),
            shipping_address={"city": "Austin", "country": "US"},
            status="delivered",
        ),
        Order(
            _id="order_017",
            user_id="user_006",
            sku="ELEC_SPEAKER_001",
            product_name="Bluetooth Speaker System",
            quantity=1,
            unit_price=199.99,
            currency="USD",
            order_date=datetime(2024, 4, 5),
            shipping_address={"city": "Austin", "country": "US"},
            status="delivered",
        ),
        Order(
            _id="order_018",
            user_id="user_006",
            sku="ELEC_HEADPHONES_001",
            product_name="Noise-Canceling Headphones",
            quantity=1,
            unit_price=349.99,
            currency="USD",
            order_date=datetime(2024, 8, 25),
            shipping_address={"city": "Austin", "country": "US"},
            status="delivered",
        ),
        Order(
            _id="order_019",
            user_id="user_006",
            sku="ELEC_GAMECONSOLE_001",
            product_name="Gaming Console Pro",
            quantity=1,
            unit_price=499.99,
            currency="USD",
            order_date=datetime(2024, 9, 15),
            shipping_address={"city": "Austin", "country": "US"},
            status="delivered",
        ),
        # User 7 - Halloween costume
        Order(
            _id="order_020",
            user_id="user_007",
            sku="HALL_COSTUME_001",
            product_name="Halloween Costume Dracula",
            quantity=1,
            unit_price=89.99,
            currency="USD",
            order_date=datetime(2025, 9, 14),
            shipping_address={"city": "Portland", "country": "US"},
            status="in-transit",
        ),
    ]

    try:
        # Generate embeddings for orders
        orders_with_embeddings = await generate_embeddings_for_orders(orders)
        
        # Upsert orders with embeddings
        for order_dict in orders_with_embeddings:
            client.db.orders.replace_one({"_id": order_dict["_id"]}, order_dict, upsert=True)
        print(f"✅ Uploaded {len(orders_with_embeddings)} orders with embeddings")

    except Exception as e:
        print(f"❌ Error uploading orders: {e}")


async def test_connection():
    client = get_atlas_client()
    if not client.client:
        print("❌ No Atlas connection available.")
        print("Set MONGODB_URI environment variable with your connection string.")
        return False
    try:
        client.client.admin.command('ping')
        print("✅ Successfully connected to MongoDB Atlas!")
        print(f"📊 Database: {client.db.name}")
        return True
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False


async def list_collections():
    client = get_atlas_client()
    if not client.client:
        print("❌ No Atlas connection available.")
        return
    try:
        collections = client.db.list_collection_names()
        print(f"📁 Collections in {client.db.name}:")
        for collection in collections:
            count = client.db[collection].count_documents({})
            print(f"  - {collection}: {count} documents")
    except Exception as e:
        print(f"❌ Error listing collections: {e}")


async def main():
    print("🚀 Setting up Orders...")
    print("=" * 50)
    if not await test_connection():
        return
    print("\n📋 Available collections:")
    await list_collections()
    print("\n🔄 Clearing old order data...")
    await clear_orders()
    print("\n🔄 Uploading orders...")
    await upload_orders()
    print("\n📊 Final collection status:")
    await list_collections()
    print("\n✅ Order setup complete!")


if __name__ == "__main__":
    asyncio.run(main())


