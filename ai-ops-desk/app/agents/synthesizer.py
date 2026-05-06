"""
Synthesizer agent — composes the final customer-facing reply.

Takes the raw outputs from the action + audit agents and asks an LLM to
write one short, warm, human reply suitable for a chat bubble. The agent
is intentionally constrained: no internal IDs unless they're already
customer-facing (refund/ticket reference numbers), no tool names, no
hallucinated facts beyond what the tools actually returned.
"""
import json
from typing import Any, Dict, List, Optional

from galileo import log

from app.models.action_output import ActionOutput


SYSTEM_PROMPT = """You are a friendly customer support assistant for Voltway, an electronics retailer.

You will be given:
- The customer's message
- A list of actions our backend just took on their behalf (with the raw API responses)

Write ONE short reply (2-4 sentences, ~50 words max) that:
- Speaks directly to the customer in a warm, natural tone
- Confirms what was done in plain English
- Includes any reference number the customer should keep (refund ID, ticket ID) if present, formatted naturally — not as JSON
- Mentions concrete amounts/currency when a refund was created
- Acknowledges frustration if the customer sounded upset, without being sycophantic
- NEVER mentions internal terms like "tool", "agent", "policy database", "tool receipt", or our internal user_id
- NEVER invents facts not present in the action data
- NEVER includes warnings, debug notes, or bracketed system text

Output ONLY the reply text. No preamble, no quotes, no markdown."""


def _summarize_actions(action_output: Optional[ActionOutput]) -> List[Dict[str, Any]]:
    """Strip tool receipts down to the fields the LLM should see."""
    if not action_output or not action_output.tool_receipts:
        return []

    summarized: List[Dict[str, Any]] = []
    for receipt in action_output.tool_receipts:
        ok = 200 <= receipt.status < 300
        resp = receipt.response or {}
        # Pick out only the customer-relevant fields per tool.
        keep: Dict[str, Any] = {"action": receipt.tool, "ok": ok}
        for key in (
            "refund_request_id",
            "ticket_id",
            "amount",
            "currency",
            "refund_status",
            "escalation_level",
            "explanation",
        ):
            if key in resp and resp[key] is not None:
                keep[key] = resp[key]
        summarized.append(keep)
    return summarized


class SynthesizerAgent:
    """Final node: turns structured action results into a customer-facing reply."""

    def __init__(self):
        from app.llm.client import openai_client
        self.llm = openai_client.client

    @log(span_type="agent", name="Synthesizer Agent Process")
    async def process(
        self,
        user_query: str,
        action_output: Optional[ActionOutput],
        error: Optional[str] = None,
    ) -> str:
        if error:
            return (
                "Sorry — something went wrong on my end before I could finish that. "
                "Please try again in a moment."
            )

        actions = _summarize_actions(action_output)
        resolution = action_output.resolution if action_output else None

        user_payload = {
            "customer_message": user_query,
            "resolution": resolution,
            "actions_taken": actions,
        }

        prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            f"Customer + actions:\n{json.dumps(user_payload, indent=2, default=str)}\n\n"
            "Reply:"
        )

        try:
            reply = await self.llm.complete(prompt, temperature=0.4, max_tokens=180)
            return (reply or "").strip().strip('"')
        except Exception as e:
            print(f"  Synthesizer failed: {e}")
            return "Thanks — I've logged your request and someone will follow up shortly."
