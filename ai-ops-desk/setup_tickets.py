"""
Setup Support Tickets for MongoDB Atlas

This script creates realistic support ticket data with JIRA-like
ticket management features including assignees, priorities, and statuses.
"""

import asyncio
import os
from dataclasses import asdict
from typing import List
from datetime import datetime, timedelta
from dotenv import load_dotenv
from app.rag.atlas_client import get_atlas_client
from app.models.ticket import Ticket

# Load environment variables from .env file
load_dotenv()

# Sentiment constants (must match ActionAgent constants)
SENTIMENT_NEGATIVE = "negative"
SENTIMENT_POSITIVE = "positive"
SENTIMENT_NEUTRAL = "neutral"


async def clear_tickets():
    """Clear all ticket documents from Atlas"""
    client = get_atlas_client()
    
    if not client.client:
        print("❌ No Atlas connection available. Set MONGODB_URI environment variable.")
        return
    
    try:
        result = client.db.tickets.delete_many({})
        print(f"🗑️  Cleared {result.deleted_count} tickets")
    except Exception as e:
        print(f"❌ Error clearing tickets: {e}")


async def upload_tickets():
    """Upload sample ticket documents to Atlas"""
    client = get_atlas_client()
    
    if not client.client:
        print("❌ No Atlas connection available. Set MONGODB_URI environment variable.")
        return
    
    print("🎫 Uploading support tickets...")
    
    # Create realistic support tickets - only for user_002
    tickets: List[Ticket] = [
        Ticket(
            _id="ticket_001",
            ticket_number="TKT-2024-001",
            user_id="user_002",
            title="Defective Drill Return Request",
            description="Customer is requesting a refund for a cordless drill that stopped working after 2 days. The battery won't hold a charge and the drill won't turn on. Customer has provided video evidence of the defect.",
            status="resolved",
            priority="high",
            assignee="employee_001",
            assignee_name="Sarah Johnson",
            created_date=datetime(2024, 8, 12, 9, 15, 0),
            updated_date=datetime(2024, 8, 18, 16, 30, 0),
            due_date=datetime(2024, 8, 19, 17, 0, 0),
            channel="email",
            customer_sentiment=SENTIMENT_NEGATIVE,
            category="refund_request",
            subcategory="defective_product",
            related_refund_requests=["refund_002"],
            order_id="order_004",
            tags=["electronics", "refund", "defective", "tools", "urgent"],
            comments={
                "2024-08-12 09:15:00": "Customer reported defective drill, provided video evidence",
                "2024-08-12 14:30:00": "Video evidence reviewed, confirmed defect. Processing refund immediately",
                "2024-08-15 10:00:00": "Refund request approved, return label sent to customer",
                "2024-08-18 16:30:00": "Return received and processed. Refund issued successfully",
            },
            resolution="Refund processed successfully. Customer received full refund within 6 days.",
            resolution_date=datetime(2024, 8, 18, 16, 30, 0),
            customer_satisfaction=5,
            escalated=False,
            escalated_to=None,
            escalated_date=None,
            time_spent_minutes=45,
            attachments=["video_defect_evidence.mp4"],
            internal_notes="Customer provided clear video evidence. Processing refund immediately.",
            created_at=datetime(2024, 8, 12, 9, 15, 0),
            updated_at=datetime(2024, 8, 18, 16, 30, 0),
        ),
        Ticket(
            _id="ticket_002",
            ticket_number="TKT-2024-002",
            user_id="user_002",
            title="Washing Machine Return Request - Size Issue",
            description="Customer is requesting a refund for a smart washing machine that is too large for their laundry room. The machine was delivered but cannot fit through the doorway. Customer wants to return it and get a smaller model.",
            status="resolved",
            priority="medium",
            assignee="employee_003",
            assignee_name="Mike Chen",
            created_date=datetime(2024, 7, 20, 14, 30, 0),
            updated_date=datetime(2024, 7, 28, 11, 45, 0),
            due_date=datetime(2024, 7, 30, 17, 0, 0),
            channel="phone",
            customer_sentiment=SENTIMENT_NEUTRAL,
            category="refund_request",
            subcategory="size_issue",
            related_refund_requests=["refund_003"],
            order_id="order_003",
            tags=["appliances", "refund", "size", "washing_machine", "return"],
            comments={
                "2024-07-20 14:30:00": "Customer called about size issue with washing machine",
                "2024-07-20 16:00:00": "Customer provided photos showing machine won't fit through doorway",
                "2024-07-22 09:15:00": "Return approved, pickup scheduled for next week",
                "2024-07-28 11:45:00": "Machine picked up and refund processed successfully",
            },
            resolution="Refund processed successfully. Customer received full refund and was provided with information about smaller models.",
            resolution_date=datetime(2024, 7, 28, 11, 45, 0),
            customer_satisfaction=4,
            escalated=False,
            escalated_to=None,
            escalated_date=None,
            time_spent_minutes=30,
            attachments=["doorway_measurements.jpg", "machine_dimensions.pdf"],
            internal_notes="Customer was very understanding about the size issue. Offered discount on smaller model.",
            created_at=datetime(2024, 7, 20, 14, 30, 0),
            updated_at=datetime(2024, 7, 28, 11, 45, 0),
        ),
        Ticket(
            _id="ticket_003",
            ticket_number="TKT-2024-003",
            user_id="user_002",
            title="Dryer Return Request - Changed Mind",
            description="Customer is requesting a refund for a smart dryer because they changed their mind about the purchase. The dryer was delivered but customer decided they don't need it after all. Item is unused and in original packaging.",
            status="resolved",
            priority="low",
            assignee="employee_004",
            assignee_name="Lisa Rodriguez",
            created_date=datetime(2024, 9, 15, 10, 20, 0),
            updated_date=datetime(2024, 9, 25, 14, 10, 0),
            due_date=datetime(2024, 9, 30, 17, 0, 0),
            channel="email",
            customer_sentiment=SENTIMENT_NEUTRAL,
            category="refund_request",
            subcategory="changed_mind",
            related_refund_requests=["refund_004"],
            order_id="order_005",
            tags=["appliances", "refund", "dryer", "return", "unused"],
            comments={
                "2024-09-15 10:20:00": "Customer emailed about returning dryer due to change of mind",
                "2024-09-15 15:30:00": "Confirmed item is unused and in original packaging",
                "2024-09-18 09:00:00": "Return label sent, pickup scheduled",
                "2024-09-25 14:10:00": "Return received and refund processed",
            },
            resolution="Refund processed successfully. Customer received full refund within 10 days.",
            resolution_date=datetime(2024, 9, 25, 14, 10, 0),
            customer_satisfaction=5,
            escalated=False,
            escalated_to=None,
            escalated_date=None,
            time_spent_minutes=20,
            attachments=[],
            internal_notes="Standard return process. Customer was polite and understanding.",
            created_at=datetime(2024, 9, 15, 10, 20, 0),
            updated_at=datetime(2024, 9, 25, 14, 10, 0),
        )
    ]
    
    try:
        # Insert new tickets (will update if _id exists)
        for ticket in tickets:
            client.db.tickets.replace_one({"_id": ticket._id}, asdict(ticket), upsert=True)
        print(f"✅ Uploaded {len(tickets)} tickets")
        
    except Exception as e:
        print(f"❌ Error uploading tickets: {e}")


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
    print("🚀 Setting up Support Tickets...")
    print("=" * 50)
    
    # Test connection first
    if not await test_connection():
        return
    
    print("\n📋 Available collections:")
    await list_collections()
    
    print("\n🔄 Clearing old ticket data...")
    await clear_tickets()
    
    print("\n🔄 Uploading tickets...")
    await upload_tickets()
    
    print("\n📊 Final collection status:")
    await list_collections()
    
    print("\n✅ Ticket setup complete!")


if __name__ == "__main__":
    asyncio.run(main())
