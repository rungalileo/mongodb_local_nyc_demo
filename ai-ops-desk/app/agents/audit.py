import time
from typing import Dict, Any, List
from pydantic import BaseModel
from datetime import datetime
from colorama import Fore, Style
from app.models.audit_output import AuditOutput, Citation
from app.models.policy_output import PolicyOutput
from app.models.records_output import RecordsOutput
from app.models.action_output import ActionOutput
from app.toggles import ToggleManager
from galileo import log


class AuditAgent:
    """A7: Audit Agent - Human-readable rationale and provenance"""
    
    def __init__(self):
        self.toggles = ToggleManager()
    
    @log(span_type="agent", name="Audit Agent Process")
    async def process(self,
                    user_query: str,
                    user_id: str,
                    policy_output: PolicyOutput,
                    records_output: RecordsOutput,
                    action_output: ActionOutput) -> Dict[str, Any]:

        print(f"  {Fore.BLUE}Generating audit trail...{Style.RESET_ALL}")
        interaction_id = f"int_{int(time.time()*1000)}"

        # Collect span IDs from all agents
        span_ids: List[str] = [
            f"policy_{int(time.time()*1000)}",
            f"records_{int(time.time()*1000)}",
            f"action_{int(time.time()*1000)}",
            f"audit_{int(time.time()*1000)}"
        ]

        # Build citations from policy context
        citations: List[Dict[str, Any]] = []

        print(f"  {Fore.BLUE}Collecting policy citations...{Style.RESET_ALL}")
        if policy_output and policy_output.policies:
            for policy in policy_output.policies:
                citations.append({
                    "source": "policy_database",
                    "doc_id": policy._id,
                    "version": policy.version,
                    "relevance_score": 0.95,  # High relevance for retrieved policies
                })
        print(f"  {Fore.BLUE}Added {len(citations)} policy citations{Style.RESET_ALL}")

        # Collect tool receipts from action agent
        tool_receipts = action_output.tool_receipts if action_output else []
        print(f"  {Fore.BLUE}Collected {len(tool_receipts)} tool receipts{Style.RESET_ALL}")

        # Generate comprehensive rationale
        print(f"  {Fore.BLUE}Generating decision rationale...{Style.RESET_ALL}")
        rationale = self._generate_rationale(user_query, user_id, policy_output, records_output, action_output)
        print(f"  {Fore.BLUE}Audit trail complete (interaction: {interaction_id}){Style.RESET_ALL}")

        return AuditOutput(
            interaction_id=interaction_id,
            span_ids=span_ids,
            citations=[Citation(**c) for c in citations],
            tool_receipts=tool_receipts,
            final_verdict=action_output.resolution if action_output else "error",
            rationale=rationale,
            created_at=datetime.utcnow().isoformat(),
        )
    
    def _generate_rationale(self,
                        user_query: str,
                        user_id: str,
                        policy_output: PolicyOutput,
                        records_output: RecordsOutput,
                        action_output: ActionOutput) -> str:
        """Generate comprehensive human-readable rationale for the decision"""
        rationale_parts = []

        # Customer request summary
        rationale_parts.append(f"Customer {user_id} submitted request: '{user_query[:100]}{'...' if len(user_query) > 100 else ''}'")

        # Policy analysis summary
        policies = policy_output.policies if policy_output else None
        if policies:
            policy_regions = list(set(p.region for p in policies))
            policy_versions = list(set(p.version for p in policies))
            rationale_parts.append(f"Retrieved {len(policies)} relevant policy documents from regions: {', '.join(policy_regions)} (versions: {', '.join(policy_versions)})")

            # Check for policy drift
            expired_policies = [p for p in policies if p.effective_until is not None]
            if expired_policies:
                rationale_parts.append(f"⚠️  Policy drift detected: Using expired policy {expired_policies[0].version} (effective until {expired_policies[0].effective_until})")
        else:
            rationale_parts.append("No relevant policies found for this request")

        # Records analysis summary
        requests = records_output.requests if records_output else []
        tickets = records_output.tickets if records_output else []
        
        if requests:
            request_statuses = [r.status for r in requests]
            request_amounts = [r.amount for r in requests if r.amount]
            total_amount = sum(request_amounts) if request_amounts else 0
            currency = requests[0].currency if requests else "USD"
            rationale_parts.append(f"Found {len(requests)} existing refund requests (statuses: {', '.join(set(request_statuses))}, total value: {currency} {total_amount:.2f})")
        else:
            rationale_parts.append("No existing refund requests found for this customer")
            
        if tickets:
            ticket_statuses = [t.status for t in tickets]
            ticket_sentiments = [t.customer_sentiment for t in tickets]
            rationale_parts.append(f"Found {len(tickets)} support tickets (statuses: {', '.join(set(ticket_statuses))}, sentiments: {', '.join(set(ticket_sentiments))})")
        else:
            rationale_parts.append("No existing support tickets found for this customer")
        
        # Action analysis summary
        tool_receipts = action_output.tool_receipts if action_output else []
        if tool_receipts:
            successful_tools = []
            failed_tools = []
            
            for receipt in tool_receipts:
                tool_name = receipt.tool
                status = receipt.status
                if 200 <= status < 300:
                    successful_tools.append(tool_name)
                else:
                    failed_tools.append(f"{tool_name} (status: {status})")
            
            if successful_tools:
                rationale_parts.append(f"✅ Successfully executed tools: {', '.join(successful_tools)}")
            if failed_tools:
                rationale_parts.append(f"❌ Failed tools: {', '.join(failed_tools)}")
                
            # Tool-specific details
            for receipt in tool_receipts:
                tool_name = receipt.tool
                response = receipt.response
                
                if tool_name == "create_refund_request":
                    refund_id = response.get("refund_request_id", "unknown")
                    amount = response.get("amount", 0)
                    currency = response.get("currency", "USD")
                    rationale_parts.append(f"  - Created refund request {refund_id} for {currency} {amount}")
                    
                elif tool_name == "create_ticket":
                    ticket_id = response.get("ticket_id", "unknown")
                    sentiment = response.get("customer_sentiment", "unknown")
                    rationale_parts.append(f"  - Created support ticket {ticket_id} (sentiment: {sentiment})")
                    
                elif tool_name == "update_ticket":
                    ticket_id = response.get("ticket_id", "unknown")
                    sentiment = response.get("customer_sentiment", "unknown")
                    rationale_parts.append(f"  - Updated support ticket {ticket_id} (new sentiment: {sentiment})")
                    
                elif tool_name == "escalate_ticket":
                    ticket_id = response.get("ticket_id", "unknown")
                    level = response.get("escalation_level", "unknown")
                    agent = response.get("assigned_agent", "unknown")
                    rationale_parts.append(f"  - Escalated ticket {ticket_id} to {level} (assigned to {agent})")
                    
                elif tool_name == "explain_refund_state":
                    explanation = response.get("explanation", "No explanation provided")
                    rationale_parts.append(f"  - Provided refund explanation: {explanation[:100]}{'...' if len(explanation) > 100 else ''}")
        else:
            rationale_parts.append("No tools were executed for this request")
        
        # Final resolution
        if action_output:
            resolution = action_output.resolution
            rationale_parts.append(f"🎯 Final resolution: {resolution}")

            # Cost summary
            cost = action_output.cost_token_usd
            if cost > 0:
                rationale_parts.append(f"💰 Total processing cost: ${cost:.4f}")
        else:
            rationale_parts.append(f"⚠️  Action agent failed - no resolution available")

        return " | ".join(rationale_parts)
