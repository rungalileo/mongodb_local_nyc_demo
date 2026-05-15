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


def _format_address(addr: Any) -> str:
    """Render a shipping_address dict on one line. Tolerant of missing keys."""
    if not isinstance(addr, dict):
        return ""
    parts = [
        addr.get("street"),
        addr.get("city"),
        addr.get("state"),
        addr.get("postal_code"),
        addr.get("country"),
    ]
    return ", ".join(p for p in parts if p)


def _render_receipt_reply(action_output: ActionOutput) -> Optional[str]:
    """If the action set produced a successful get_receipt, render it as a
    deterministic chat reply. Returns None when no receipt is present so the
    caller falls back to the LLM-based synthesizer.

    Templated rather than LLM-generated so the demo is reliable: full field
    coverage, no truncation, identical output every run.
    """
    if not action_output or not action_output.tool_receipts:
        return None
    receipt = next(
        (
            r for r in action_output.tool_receipts
            if r.tool == "get_receipt" and 200 <= r.status < 300
        ),
        None,
    )
    if not receipt:
        return None
    resp = receipt.response or {}

    product = resp.get("product_name") or "your item"
    sku = resp.get("sku") or ""
    qty = resp.get("quantity") or 1
    unit_price = resp.get("unit_price")
    total = resp.get("total_amount")
    currency = resp.get("currency") or "USD"
    order_id = resp.get("order_id") or ""
    order_date = resp.get("order_date") or ""
    address = _format_address(resp.get("shipping_address"))
    order_status = resp.get("order_status") or ""

    # Normalize order_date to just the date part if it looks like an ISO ts.
    if isinstance(order_date, str) and "T" in order_date:
        order_date = order_date.split("T", 1)[0]

    lines: List[str] = [
        f"Here are the details for that order:",
        "",
        f"• Product: {product}",
    ]
    if sku:
        lines.append(f"• SKU: {sku}")
    if order_id:
        lines.append(f"• Order ID: {order_id}")
    if order_date:
        lines.append(f"• Purchased: {order_date}")
    if unit_price is not None:
        lines.append(f"• Unit price: {currency} {float(unit_price):.2f}")
    lines.append(f"• Quantity: {qty}")
    if total is not None:
        lines.append(f"• Total paid: {currency} {float(total):.2f}")
    if address:
        lines.append(f"• Shipping to: {address}")
    if order_status:
        lines.append(f"• Status: {order_status}")
    lines.append("")
    lines.append("Let me know if you'd like to start a return or anything else.")
    return "\n".join(lines)


def _render_blocked_refund_reply(action_output: ActionOutput) -> Optional[str]:
    """If create_refund_request was blocked by Agent Control, render a clear
    'cannot process, escalating' reply. Returns None when not applicable.

    Deterministic so the demo doesn't risk the LLM confusing this with the
    stale explain_refund_state output (which still reports the prior refund
    as paid) and telling the customer the refund went through.
    """
    if not action_output or not action_output.tool_receipts:
        return None
    blocked = next(
        (
            r for r in action_output.tool_receipts
            if r.tool == "create_refund_request"
            and r.status == 412
            and (r.response or {}).get("error") == "blocked_by_agent_control"
        ),
        None,
    )
    if not blocked:
        return None

    escalated = any(
        r.tool == "escalate_ticket" and 200 <= r.status < 300
        for r in action_output.tool_receipts
    )
    # Reference the create/update ticket id rather than escalate_ticket's,
    # because escalate_ticket currently rolls a brand-new random id and the
    # UI's ticket badge comes from create/update. Keeping these in sync
    # avoids the "badge says TKT_A, message says TKT_B" mismatch.
    ticket_id: Optional[str] = None
    for preferred_tool in ("create_ticket", "update_ticket", "escalate_ticket"):
        match = next(
            (
                r for r in action_output.tool_receipts
                if r.tool == preferred_tool and 200 <= r.status < 300
            ),
            None,
        )
        if match:
            ticket_id = (match.response or {}).get("ticket_id")
            if ticket_id:
                break

    lines: List[str] = [
        "I'm not able to process this refund right now — our compliance "
        "checks flagged it and I want to make sure we get the amount right "
        "before charging anything back to your account.",
        "",
    ]
    if escalated:
        if ticket_id:
            lines.append(
                f"I've escalated this to a specialist on our team "
                f"(reference {ticket_id}) and they'll reach out shortly to "
                "confirm the correct refund amount and finish the return."
            )
        else:
            lines.append(
                "I've escalated this to a specialist on our team and they'll "
                "reach out shortly to confirm the correct refund amount and "
                "finish the return."
            )
    else:
        lines.append(
            "A specialist on our team will follow up shortly to confirm "
            "the correct refund amount and finish the return."
        )
    lines.append("")
    lines.append("Sorry for the extra step here — appreciate your patience.")
    return "\n".join(lines)


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

        # Deterministic templated replies for demo-critical paths. These run
        # before the LLM so we don't risk the LLM concocting a misleading
        # reply (e.g. saying "refund processed" when create_refund_request
        # was blocked but explain_refund_state surfaced a stale prior
        # refund's "paid" status).
        if action_output is not None:
            blocked = _render_blocked_refund_reply(action_output)
            if blocked:
                return blocked
            templated = _render_receipt_reply(action_output)
            if templated:
                return templated

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
