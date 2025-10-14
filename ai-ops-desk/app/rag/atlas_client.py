"""
MongoDB Atlas client for RAG operations

Handles connections to MongoDB Atlas, vector search, and aggregation queries
for the AI Operations Desk.
"""

import os
import logging
from typing import Dict, List, Any, Optional
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from galileo import log

logger = logging.getLogger(__name__)


class AtlasClient:
    """MongoDB Atlas client with vector search and aggregation capabilities"""
    
    def __init__(self, connection_string: Optional[str] = None):
        self.connection_string = connection_string or os.getenv("MONGODB_URI")
        self.client = None
        self.db = None
        
        if self.connection_string:
            try:
                # Create a new client and connect to the server
                self.client = MongoClient(self.connection_string, server_api=ServerApi('1'))
                # Send a ping to confirm a successful connection
                self.client.admin.command('ping')
                self.db = self.client.ai_ops_desk
                logger.info("Successfully connected to MongoDB Atlas!")
            except Exception as e:
                logger.error(f"Could not connect to MongoDB Atlas: {e}")
                raise ConnectionError(f"Failed to connect to MongoDB Atlas: {e}")
        else:
            raise ValueError("No MongoDB connection string provided. Set MONGODB_URI environment variable.")

    @log(span_type="tool", name="Vector Search Policies")
    async def search_vector_policies(self, user_query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search policies using vector similarity"""
        
        # Generate embedding for the query text
        from app.llm.client import openai_client
        query_embedding = await openai_client.client.embed([user_query])
        query_vector = query_embedding[0].tolist()
        
        # Vector search using aggregation pipeline
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "policy_vectors",
                    "path": "embedding",
                    "queryVector": query_vector,
                    "numCandidates": limit * 10,
                    "limit": limit
                }
            }
        ]
        
        results = list(self.db.policies.aggregate(pipeline))
        
        # Remove embeddings from results to reduce payload size
        for policy in results:
            policy.pop("embedding", None)
        
        return results

    @log(span_type="tool", name="Get User Refund Requests")
    async def get_user_refund_requests(self, user_id: str) -> List[Dict[str, Any]]:
        """Get refund requests for a specific user"""
        query = {"user_id": user_id}
        results = list(self.db.refund_requests.find(query))
        return results

    @log(span_type="tool", name="Get User Tickets")
    async def get_user_tickets(self, user_id: str) -> List[Dict[str, Any]]:
        """Get tickets for a specific user"""
        query = {"user_id": user_id}
        results = list(self.db.tickets.find(query))
        return results
    
    @log(span_type="tool", name="Get User Orders")
    async def get_user_orders(self, user_id: str, query_text: str = None) -> List[Dict[str, Any]]:
        """Get orders for a specific user, optionally using vector search for relevance"""
        print(f"[ATLAS] Getting orders for user_id: {user_id}, query_text: {query_text}")
        
        # First, let's check what orders exist for this user (debugging)
        # all_orders = list(self.db.orders.find({"user_id": user_id}))
        if query_text:
            # Use vector search to find most relevant order
            from app.llm.client import openai_client
            query_embedding = await openai_client.client.embed([query_text])
            query_vector = query_embedding[0].tolist()
            
            # Vector search pipeline with user filter
            pipeline = [
                {
                    "$vectorSearch": {
                        "index": "order_index",
                        "path": "embedding",
                        "queryVector": query_vector,
                        "numCandidates": 10,
                        "limit": 1,
                        "filter": {"user_id": user_id}  # Filter during vector search
                    }
                }
            ]
            
            try:
                results = list(self.db.orders.aggregate(pipeline))
                # Remove embeddings from results to reduce payload size
                for order in results:
                    order.pop("embedding", None)
                return results
            except Exception as e:
                print(f"[ATLAS] Vector search failed: {e}")
                print(f"[ATLAS] Pipeline was: {pipeline}")
                return []
        else:
            # Fallback to simple user_id query
            query = {"user_id": user_id}
            results = list(self.db.orders.find(query).limit(1))
            # Remove embeddings from results to reduce payload size
            for order in results:
                order.pop("embedding", None)
            print(f"[ATLAS] Simple query results: {len(results)} orders found")
            return results

    @log(span_type="tool", name="Create Audit Record")
    async def create_audit_record(self, audit_data: Dict[str, Any]) -> bool:
        """Create a new audit record"""
        result = self.db.audits.insert_one(audit_data)
        return result.inserted_id is not None


# Global instance
_atlas_client = None


def get_atlas_client() -> AtlasClient:
    """Get the global Atlas client instance"""
    global _atlas_client
    if _atlas_client is None:
        _atlas_client = AtlasClient()
    return _atlas_client