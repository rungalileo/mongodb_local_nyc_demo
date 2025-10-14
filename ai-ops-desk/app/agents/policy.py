"""
A2: Policy Agent - Knowledge synthesis using MongoDB Atlas RAG

Uses Atlas Vector Search over `policies` and Atlas Search over `fulltext`
Output: {
  "ctx": [{"doc_id": "...", "version": "v23", "region": "EU", "span": [432,597]}],
  "answer_draft": "Policy v23 applies to EU electronics…",
  "required_clauses_present": ["refund_window","category_electronics"],
  "required_clauses_missing": []
}

Emits: ContextGrounding (0–1), ContextCoverage (0–1), Overreach (% extra, optional)
"""

import time
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from app.models.policy import Policy as PolicyModel
from app.models.policy_output import PolicyOutput
from app.models.order import Order
from app.rag.queries import get_policy_context
from app.llm.client import openai_client
from datetime import datetime
from app.toggles import ToggleManager
from galileo import log

class PolicyAgent:
    """A2: Policy Agent - Knowledge synthesis using RAG"""
    
    def __init__(self):
        self.llm = openai_client.client
        self.toggles = ToggleManager()
    
    @log(span_type="agent", name="Policy Agent Process")
    async def process(self, user_query: str, user_id: str, order:Order | None) -> PolicyOutput:
        
        print(f"[POLICY] Processing query for {user_id}: { user_query[:100]}...")
        
        
        # Handle case where order is None
        if order is None:
            print(f"[POLICY] No order found for user {user_id}, using default US region")
            region = "US"
        else:
            # Determine region from order shipping address
            country = order.shipping_address.get("country", "").upper()
            if country in ["US", "USA", "UNITED STATES"]:
                region = "US"
            elif country in ["UK", "GB", "UNITED KINGDOM", "FR", "FRANCE", "DE", "GERMANY", "IT", "ITALY", "ES", "SPAIN"]:
                region = "EU"
            else:
                region = "EU"  # Default to EU
        
        # Get policy context using RAG
        policy_context = await get_policy_context(user_query, region)
        
        # Sort policies by effective_from in increasing order
        policies_to_use = policy_context["policies"]
        if policies_to_use:
            policies_to_use.sort(key=lambda x: x.get("effective_from", datetime.min))

        # Coerce dicts to PolicyModel; ignore extra fields gracefully
        typed_policies: List[PolicyModel] = []
        for p in policies_to_use:
            try:
                typed_policies.append(PolicyModel(**p))
            except Exception:
                # If schema mismatch, keep minimal required fields
                minimal = {k: p.get(k) for k in ["_id","region","version","effective_from","effective_until","clauses","fulltext","refund_window_days","exclusions"] if k in p}
                typed_policies.append(PolicyModel(**minimal))
        output = PolicyOutput(policies=typed_policies)
        return output
    