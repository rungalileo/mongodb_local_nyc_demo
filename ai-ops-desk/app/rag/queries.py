"""
RAG query functions for MongoDB Atlas

High-level query functions used by agents to retrieve context and data.
"""

from typing import Dict, List, Any, Optional
from app.rag.atlas_client import get_atlas_client
from app.models.order import Order
from galileo import log


@log(span_type="workflow", name="Search Vector Policies")
async def search_vector_policies(user_query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Search policies using vector similarity"""
    client = get_atlas_client()
    return await client.search_vector_policies(user_query, limit)


@log(span_type="workflow", name="Get User Refund Requests")
async def get_user_refund_requests(user_id: str) -> List[Dict[str, Any]]:
    """Get claims for a specific user"""
    client = get_atlas_client()
    return await client.get_user_refund_requests(user_id)


@log(span_type="workflow", name="Get User Tickets")
async def get_user_tickets(user_id: str) -> List[Dict[str, Any]]:
    """Get tickets for a specific user"""
    client = get_atlas_client()
    return await client.get_user_tickets(user_id)


@log(span_type="workflow", name="Get User Order")
async def get_user_order(user_id: str, query: str) -> List[Dict[str, Any]]:
    """Get orders for a specific user using vector search for relevance"""
    client = get_atlas_client()
    orders = await client.get_user_orders(user_id, query_text=query)
    
    return orders  # Already limited to 1 by vector search


@log(span_type="workflow", name="Get Policy Context")
async def get_policy_context(user_query: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Get comprehensive policy context for a query"""
    
    # Vector search
    vector_results = await search_vector_policies(user_query, limit=10)
    
    # Filter by region if specified
    if region:
        vector_results = [p for p in vector_results if p.get("region") == region]
    
    # Remove embeddings from results to reduce payload size
    for policy in vector_results:
        policy.pop("embedding", None)
    
    # Return all matching policies
    context = {
        "policies": vector_results,
        "region": region,
        "query": user_query
    }
    
    return context


@log(span_type="workflow", name="Create Audit Record")
async def create_audit_record(audit_data: Dict[str, Any]) -> bool:
    """Create an audit record"""
    client = get_atlas_client()
    return await client.create_audit_record(audit_data)