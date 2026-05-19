"""
Setup Refund Requests for MongoDB Atlas

This script creates realistic refund request data with all relevant
financial and tracking information.
"""

import asyncio
import os
from dataclasses import asdict
from typing import List
from datetime import datetime, timedelta
from dotenv import load_dotenv
from app.rag.atlas_client import get_atlas_client
from app.models.refund_request import RefundRequest

# Load environment variables from .env file
load_dotenv()


async def clear_refund_requests():
    """Clear all refund request documents from Atlas"""
    client = get_atlas_client()
    
    if not client.client:
        print("❌ No Atlas connection available. Set MONGODB_URI environment variable.")
        return
    
    try:
        result = client.db.refund_requests.delete_many({})
        print(f"🗑️  Cleared {result.deleted_count} refund requests")
    except Exception as e:
        print(f"❌ Error clearing refund requests: {e}")


async def upload_refund_requests():
    """Upload sample refund request documents to Atlas"""
    client = get_atlas_client()
    
    if not client.client:
        print("❌ No Atlas connection available. Set MONGODB_URI environment variable.")
        return
    
    print("💰 Uploading refund requests...")
    
    # Create realistic refund requests with various statuses and scenarios
    refund_requests: List[RefundRequest] = [
        # User 2 - returned all items (has tickets)
        RefundRequest(
            _id="refund_002",
            user_id="user_002",
            sku="ELEC_DRILL_001",
            product_name="Cordless Drill Set",
            amount=199.99,
            currency="USD",
            status="paid",
            filed_date=datetime(2024, 8, 12, 9, 15, 0),
            purchase_date=datetime(2024, 8, 10),
            reason="defective_product",
            description="Drill stopped working after 2 days, battery won't hold charge",
            related_tickets=["ticket_001"],
            order_id="order_004",
            refund_method="original_payment",
            expected_refund_date=datetime(2024, 8, 19),
            actual_refund_date=datetime(2024, 8, 18),
            processed_by="employee_002",
            notes="Customer provided video evidence of defect",
            category="electronics",
            subcategory="tools",
            warranty_covered=True,
            return_shipping_required=True,
            return_tracking_number="RET987654321",
            created_at=datetime(2024, 8, 12, 9, 15, 0),
            updated_at=datetime(2024, 8, 18, 16, 30, 0),
        ),
        RefundRequest(
            _id="refund_003",
            user_id="user_002",
            sku="ELEC_WASHER_001",
            product_name="Smart Washing Machine",
            amount=899.99,
            currency="USD",
            status="paid",
            filed_date=datetime(2024, 7, 20, 14, 30, 0),
            purchase_date=datetime(2024, 7, 15),
            reason="size_issue",
            description="Washing machine too large for laundry room doorway",
            related_tickets=["ticket_002"],
            order_id="order_003",
            refund_method="original_payment",
            expected_refund_date=datetime(2024, 7, 30),
            actual_refund_date=datetime(2024, 7, 28),
            processed_by="employee_003",
            notes="Customer provided photos showing size issue. Offered discount on smaller model.",
            category="appliances",
            subcategory="washing_machine",
            warranty_covered=False,
            return_shipping_required=True,
            return_tracking_number="RET123456789",
            created_at=datetime(2024, 7, 20, 14, 30, 0),
            updated_at=datetime(2024, 7, 28, 11, 45, 0),
        ),
        RefundRequest(
            _id="refund_004",
            user_id="user_002",
            sku="ELEC_DRYER_002",
            product_name="Smart Dryer",
            amount=200.00,
            currency="USD",
            status="paid",
            filed_date=datetime(2024, 9, 15, 10, 20, 0),
            purchase_date=datetime(2024, 9, 10),
            reason="changed_mind",
            description="Customer changed mind about purchase, item unused in original packaging",
            related_tickets=["ticket_003"],
            order_id="order_005",
            refund_method="original_payment",
            expected_refund_date=datetime(2024, 9, 30),
            actual_refund_date=datetime(2024, 9, 25),
            processed_by="employee_004",
            notes="Standard return process. Customer was polite and understanding.",
            category="appliances",
            subcategory="dryer",
            warranty_covered=False,
            return_shipping_required=True,
            return_tracking_number="RET456789123",
            created_at=datetime(2024, 9, 15, 10, 20, 0),
            updated_at=datetime(2024, 9, 25, 14, 10, 0),
        ),
        # User 1 - stale prior refund used by the "refund compliance" demo.
        # This is an unrelated premium-audio refund from earlier in the year.
        # The buggy _create_refund_request_checked tool grabs THIS amount
        # ($679.00) when asked to refund the headphones order ($699.98). The
        # delta is intentionally small (~$20) so the bug is subtle —
        # plausible, easy to miss in a manual review, but exactly the class
        # of off-by-some-amount mistake an LLM-judge metric + the
        # refund-compliance Agent Control rule are meant to catch.
        RefundRequest(
            _id="refund_005",
            user_id="user_001",
            sku="ELEC_SOUNDBAR_001",
            product_name="Premium Soundbar",
            amount=679.00,
            currency="USD",
            status="paid",
            filed_date=datetime(2026, 2, 4, 11, 0, 0),
            purchase_date=datetime(2026, 1, 30),
            reason="changed_mind",
            description="Customer upgraded to a different audio setup; soundbar returned unused.",
            related_tickets=[],
            order_id="order_legacy_soundbar",
            refund_method="original_payment",
            expected_refund_date=datetime(2026, 2, 10),
            actual_refund_date=datetime(2026, 2, 8),
            processed_by="employee_005",
            notes="Standard return — item unopened, in original packaging.",
            category="electronics",
            subcategory="audio",
            warranty_covered=False,
            return_shipping_required=True,
            return_tracking_number="RET112233445",
            created_at=datetime(2026, 2, 4, 11, 0, 0),
            updated_at=datetime(2026, 2, 8, 14, 0, 0),
        ),
    ]
    
    try:
        # Insert new refund requests (will update if _id exists)
        for refund in refund_requests:
            client.db.refund_requests.replace_one({"_id": refund._id}, asdict(refund), upsert=True)
        print(f"✅ Uploaded {len(refund_requests)} refund requests")
        
    except Exception as e:
        print(f"❌ Error uploading refund requests: {e}")


async def test_connection():
    """Test Atlas connection"""
    client = get_atlas_client()
    
    if not client.client:
        print("❌ No Atlas connection available.")
        print("Set MONGODB_URI environment variable with your connection string.")
        return False
    
    try:
        # Test ping
        client.client.admin.command('ping')
        print("✅ Successfully connected to MongoDB Atlas!")
        print(f"📊 Database: {client.db.name}")
        return True
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False


async def list_collections():
    """List all collections in the database"""
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
    """Main setup function"""
    print("🚀 Setting up Refund Requests...")
    print("=" * 50)
    
    # Test connection first
    if not await test_connection():
        return
    
    print("\n📋 Available collections:")
    await list_collections()
    
    print("\n🔄 Clearing old refund request data...")
    await clear_refund_requests()
    
    print("\n🔄 Uploading refund requests...")
    await upload_refund_requests()
    
    print("\n📊 Final collection status:")
    await list_collections()
    
    print("\n✅ Refund request setup complete!")


if __name__ == "__main__":
    asyncio.run(main())
