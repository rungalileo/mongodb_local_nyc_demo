#!/usr/bin/env python3
"""
Setup script for MongoDB Atlas Vector Search

This script helps you:
1. Generate real embeddings for policy documents
2. Upload them to Atlas with proper vector data
3. Verify the setup is working
"""

import asyncio
import os
from dataclasses import asdict
from typing import List
from datetime import datetime
from dotenv import load_dotenv
from app.rag.atlas_client import get_atlas_client
from app.llm.client import openai_client
from app.models.policy import Policy

# Load environment variables
load_dotenv()


async def clear_policies():
    """Clear all policy documents from Atlas"""
    client = get_atlas_client()
    
    if not client.client:
        print("❌ No Atlas connection available. Set MONGODB_URI environment variable.")
        return
    
    try:
        result = client.db.policies.delete_many({})
        print(f"🗑️  Cleared {result.deleted_count} policies")
    except Exception as e:
        print(f"❌ Error clearing policies: {e}")


# Policy data configuration
POLICY_DATA: List[Policy] = [
    Policy(
        _id="policy_eu_current_001",
        region="EU",
        version="v24.1",
        effective_from=datetime(2024, 8, 1),
        effective_until=None,
        clauses=["refund_window", "category_electronics", "region_scope"],
        fulltext="EU Electronics Return Policy v24.1: Customers in the European Union may return electronics within 14 days of purchase. This applies to all electronic devices excluding custom-built items. Refunds will be processed in the original currency.",
        refund_window_days=14,
        exclusions=["custom_built"],
    ),
    Policy(
        _id="policy_us_current_001",
        region="US",
        version="v24.1",
        effective_from=datetime(2024, 8, 1),
        effective_until=None,
        clauses=["refund_window", "category_electronics", "region_scope"],
        fulltext="US Electronics Return Policy v24.1: Customers in the United States may return electronics within 30 days of purchase. This applies to all electronic devices. Refunds will be processed in USD.",
        refund_window_days=30,
        exclusions=[],
    ),
    Policy(
        _id="policy_eu_previous_001",
        region="EU",
        version="v23.2",
        effective_from=datetime(2020, 1, 1),
        effective_until=datetime(2024, 7, 31),
        clauses=["refund_window", "category_electronics"],
        fulltext="EU Electronics Return Policy v23.2: Customers may return electronics within 10 days. Previous policy with shorter window.",
        refund_window_days=10,
        exclusions=["custom_built", "opened_software"],
    ),
]


async def generate_embeddings_for_policies():
    """Generate real embeddings for policy documents"""
    
    print("🔄 Generating embeddings for policy documents...")
    
    # Extract fulltext from policy data
    policy_texts = [policy.fulltext for policy in POLICY_DATA]
    
    # Generate embeddings
    embeddings = await openai_client.client.embed(policy_texts)
    print(f"✅ Generated {len(embeddings)} embeddings")
    
    return embeddings


async def upload_policies_with_embeddings():
    """Upload policies with real embeddings to Atlas"""
    
    client = get_atlas_client()
    
    if not client.client:
        print("❌ No Atlas connection available. Set MONGODB_URI environment variable.")
        return False
    
    print("📄 Uploading policies with embeddings...")
    
    # Generate embeddings
    embeddings = await generate_embeddings_for_policies()
    
    # Create policy documents with real embeddings
    policies = []
    for i, policy in enumerate(POLICY_DATA):
        policy_doc = asdict(policy)
        policy_doc["embedding"] = embeddings[i].tolist()
        policies.append(policy_doc)
    
    try:
        # Upload policies
        for policy in policies:
            client.db.policies.replace_one({"_id": policy["_id"]}, policy, upsert=True)
        
        print(f"✅ Uploaded {len(policies)} policies with embeddings")
        return True
        
    except Exception as e:
        print(f"❌ Error uploading policies: {e}")
        return False


async def test_vector_search():
    """Test vector search functionality"""
    
    print("🔍 Testing vector search...")
    
    try:
        client = get_atlas_client()
        
        # Test search
        results = await client.search_vector_policies("refund electronics", limit=3)
        
        print(f"✅ Vector search returned {len(results)} results")
        for i, result in enumerate(results):
            print(f"  {i+1}. {result.get('_id')} - {result.get('version')} ({result.get('region')})")
        
        return True
        
    except Exception as e:
        print(f"❌ Vector search test failed: {e}")
        print("\n💡 Make sure you have:")
        print("   1. Created a vector search index named 'policy_vectors'")
        print("   2. Set the embedding field to 'embedding'")
        print("   3. Set dimensions to 1536")
        return False


async def main():
    """Main setup function"""
    
    print("🚀 Setting up MongoDB Atlas Vector Search")
    print("=" * 50)
    
    # Step 0: Clear existing policies
    print("\n🔄 Clearing existing policies...")
    await clear_policies()
    
    # Step 1: Upload policies with embeddings
    success = await upload_policies_with_embeddings()
    if not success:
        return
    
    print("\n" + "=" * 50)
    
    # Step 2: Test vector search
    await test_vector_search()
    
    print("\n" + "=" * 50)
    print("✅ Setup complete!")


if __name__ == "__main__":
    asyncio.run(main())
