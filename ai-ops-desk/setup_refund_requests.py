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
        # User 2 - returned drill (has tickets)
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
        )
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
