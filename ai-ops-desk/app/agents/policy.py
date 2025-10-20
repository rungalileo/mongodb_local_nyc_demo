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
from colorama import Fore, Style
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
    async def process(self, 
                    user_query: str, 
                    user_id: str, 
                    order:Order | None) -> PolicyOutput:
        
        print(f"  {Fore.CYAN}Processing query: {user_query[:80]}...{Style.RESET_ALL}")
        # import pdb;pdb.set_trace()

        # Handle case where order is None
        if order is None:
            print(f"  {Fore.CYAN}No order found for {user_id}, defaulting to US region{Style.RESET_ALL}")
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
            print(f"  {Fore.CYAN}Determined region: {region} (from country: {country}){Style.RESET_ALL}")

        # Check if we should force old version (for drift scenario)
        use_latest = not self.toggles.policy_force_old_version

        if not use_latest:
            print(f"  {Fore.YELLOW}⚠️  Using old policy version (drift mode enabled){Style.RESET_ALL}")

        print(f"  {Fore.CYAN}Searching policies via vector search (region: {region})...{Style.RESET_ALL}")
        # Get policy context using RAG
        policy_context = await get_policy_context(user_query, region)
        
        # If drift scenario, potentially use older version
        if not use_latest and policy_context["policies"]:
            # Use expired policies (those with effective_until dates)
            expired_policies = [p for p in policy_context["policies"]
                                if p.get("effective_until") is not None]

            if expired_policies:
                # Sort by effective_from date (newest first) and take the most recent expired policy
                expired_policies.sort(key=lambda x: x.get("effective_from", datetime.min), reverse=True)
                policy_context["policies"] = expired_policies
                policy_context["latest_policy"] = expired_policies[0]
                print(f"  {Fore.YELLOW}Applied expired policy: {expired_policies[0].get('version')} ({expired_policies[0].get('effective_from')} to {expired_policies[0].get('effective_until')}){Style.RESET_ALL}")
                policies_to_use = expired_policies
            else:
                # No expired policies found, use current policies
                policies_to_use = policy_context["policies"]
                print(f"  {Fore.CYAN}Using current policies (no expired policies found){Style.RESET_ALL}")
        else:
            policies_to_use = policy_context["policies"]
            print(f"  {Fore.CYAN}Found {len(policies_to_use)} relevant policies{Style.RESET_ALL}")

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
    