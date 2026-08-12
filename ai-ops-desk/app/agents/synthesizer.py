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


def _offer_label(description: Optional[str], code: Optional[str]) -> str:
    """Human-facing name for a promo, for customer copy.

    Promos are pitched as named *offers* (e.g. "QMobile partner promotion",
    "Fall Ending Sale"), never as raw codes like ``QMOBILE`` — QMobile is a
    promotional partner, not a coupon code. We take the offer name from the part
    of the seeded description before the em/en dash, falling back to a
    title-cased code if no description is present.
    """
    if description:
        # Descriptions read "<offer name> — <details>"; keep the offer name.
        for sep in (" — ", " – ", " - "):
            if sep in description:
                return description.split(sep, 1)[0].strip()
        return description.strip()
    if code:
        return f"{code.replace('-', ' ').title()} promotion"
    return "promotion"


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
        f"Here's the receipt for your {product}.",
        "",
        "Let me know if you'd like to start a return or anything else.",
    ]
    return "\n".join(lines)


def _render_blocked_refund_reply(action_output: ActionOutput) -> Optional[str]:
    """If create_refund_request was blocked by Agent Control, render a clean
    customer-facing refund confirmation that uses the receipt amount instead
    of the (wrong) amount the agent tried.

    Treats the deny outcome as if the system silently corrected to the right
    amount: the customer sees a normal "refund processed for $X" message.
    Demo intent is that the audience compares this run (control on) against
    a control-off run where the agent confidently refunds the wrong amount.
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

    resp = blocked.response or {}
    receipt_amount = resp.get("receipt_amount")
    currency = resp.get("currency") or "USD"
    product = resp.get("product_name") or "your order"

    # Without a receipt amount we can't honestly fabricate a number, so fall
    # back to the older "we'll follow up" copy.
    if receipt_amount is None:
        return (
            "Thanks for reaching out. A specialist on our team will follow up "
            "shortly to confirm the refund details and finish the return."
        )

    try:
        amount_str = f"{currency} {float(receipt_amount):.2f}"
    except (TypeError, ValueError):
        amount_str = f"{currency} {receipt_amount}"

    lines: List[str] = [
        f"All set — I've processed a refund of {amount_str} for {product}.",
        "",
        "You should see the credit on your original payment method within "
        "5–7 business days. Is there anything else I can help with?",
    ]
    return "\n".join(lines)


def _render_discount_reply(action_output: Optional[ActionOutput]) -> Optional[str]:
    """If apply_discount succeeded, render a warm confirmation naming the promo,
    the amount saved, and the new price. Templated (not LLM-generated) so the
    demo is deterministic. Returns None when no discount was applied.

    NOTE: the reply intentionally reads as a normal, confident confirmation —
    the agent has no idea the promo was expired. That gap between the cheerful
    customer message and the expired-promo signal in the trace is the point of
    the demo.
    """
    if not action_output or not action_output.tool_receipts:
        return None
    applied = next(
        (
            r for r in action_output.tool_receipts
            if r.tool == "apply_discount" and 200 <= r.status < 300
        ),
        None,
    )
    if not applied:
        return None

    resp = applied.response or {}
    product = resp.get("product_name") or "your item"
    currency = resp.get("currency") or "USD"
    offer = _offer_label(resp.get("promo_description"), resp.get("promo_code"))
    discount = resp.get("discount_usd")
    final_price = resp.get("final_price")

    def _money(value: Any) -> str:
        try:
            return f"{currency} {float(value):.2f}"
        except (TypeError, ValueError):
            return f"{currency} {value}"

    saved = _money(discount) if discount is not None else "a discount"
    price_line = (
        f" Your new price is {_money(final_price)}." if final_price is not None else ""
    )
    return (
        f"Good news — I applied the {offer} to the {product}, saving you {saved}."
        f"{price_line} I've added it to your cart. Anything else I can help with?"
    )


def _render_promo_propose_reply(action_output: Optional[ActionOutput]) -> Optional[str]:
    """Turn 1 of the two-turn promo flow: the agent looked up promotions and is
    proposing the best one, asking the customer to confirm before applying.

    Only fires when check_promotions found a promo to propose AND no
    apply_discount happened this turn (so we don't collide with the applied /
    blocked replies). Templated for a deterministic demo.

    Like the applied reply, the copy is cheerfully confident — the agent has no
    idea the "best deal" it's pitching already lapsed. That's the setup; the
    expired-promo signal in the trace is the payoff.
    """
    if not action_output or not action_output.tool_receipts:
        return None

    # If a discount was applied or blocked this turn, this is not a propose turn.
    if any(r.tool == "apply_discount" for r in action_output.tool_receipts):
        return None

    check = next(
        (
            r for r in action_output.tool_receipts
            if r.tool == "check_promotions" and 200 <= r.status < 300
        ),
        None,
    )
    if not check:
        return None

    resp = check.response or {}
    code = resp.get("proposed_promo_code")
    if not code:
        return None

    product = resp.get("product_name") or "that item"
    currency = resp.get("currency") or "USD"
    offer = _offer_label(resp.get("proposed_promo_description"), code)
    discount = resp.get("proposed_discount_usd")
    final_price = resp.get("proposed_final_price")
    list_price = resp.get("list_price")

    def _money(value: Any) -> str:
        try:
            return f"{currency} {float(value):,.2f}"
        except (TypeError, ValueError):
            return f"{currency} {value}"

    saved = _money(discount) if discount is not None else "a discount"
    list_line = f" (normally {_money(list_price)})" if list_price is not None else ""
    price_line = (
        f", saving you {saved} that brings it to {_money(final_price)}{list_line}"
        if final_price is not None else f", saving you {saved}"
    )
    return (
        f"Great news — Voltway is running the {offer} on the {product}"
        f"{price_line}. Want me to apply it and add it to your cart?"
    )


def _render_blocked_discount_reply(action_output: Optional[ActionOutput]) -> Optional[str]:
    """If apply_discount was blocked by Agent Control (expired promo), render a
    clean "that offer has expired, price unchanged" reply.

    This is the control-on remediation: the agent tried to apply a stale promo,
    the guard stopped it, and instead of quietly discounting we keep the full
    price and tell the customer the code lapsed. Demo intent: compare this run
    against a control-off run where the agent confidently gives away the
    expired discount.
    """
    if not action_output or not action_output.tool_receipts:
        return None
    blocked = next(
        (
            r for r in action_output.tool_receipts
            if r.tool == "apply_discount"
            and r.status == 412
            and (r.response or {}).get("error") == "blocked_by_agent_control"
        ),
        None,
    )
    if not blocked:
        return None

    resp = blocked.response or {}
    product = resp.get("product_name") or "that item"
    currency = resp.get("currency") or "USD"
    offer = _offer_label(resp.get("promo_description"), resp.get("promo_code"))
    list_price = resp.get("list_price")
    end_date = resp.get("promo_end_date") or ""
    if isinstance(end_date, str) and "T" in end_date:
        end_date = end_date.split("T", 1)[0]

    def _money(value: Any) -> str:
        try:
            return f"{currency} {float(value):,.2f}"
        except (TypeError, ValueError):
            return f"{currency} {value}"

    price_line = (
        f" the {product} stays at {_money(list_price)}"
        if list_price is not None else f" the {product} stays at full price"
    )
    ended = f" (it ended on {end_date})" if end_date else ""
    return (
        f"I'm sorry, but the {offer} has expired{ended}, so I wasn't able to apply it —"
        f"{price_line}. I can let you know if a new offer comes up, or help with anything else."
    )


def _render_promo_declined_reply(action_output: Optional[ActionOutput]) -> Optional[str]:
    """Customer tapped "No thanks" on a proposed promo. The action agent cleared
    the pending offer and set resolution=promo_declined (no tools run). Render a
    friendly acknowledgement so we don't fall through to generic handling.
    """
    if not action_output:
        return None
    if getattr(action_output, "resolution", None) != "promo_declined":
        return None
    return (
        "No problem — I won't apply that offer. If you change your mind or want me "
        "to check for other deals, just let me know. Anything else I can help with?"
    )


def _render_no_promo_reply(action_output: Optional[ActionOutput]) -> Optional[str]:
    """Turn 1, control-on remediation: Agent Control steered the agent away from
    an expired offer at proposal time and there was no live promo to fall back
    to. Instead of pitching a stale code, tell the customer there's no current
    promotion. Fires only when check_promotions flagged ``no_active_promo`` and
    no apply happened this turn.
    """
    if not action_output or not action_output.tool_receipts:
        return None
    if any(r.tool == "apply_discount" for r in action_output.tool_receipts):
        return None
    check = next(
        (
            r for r in action_output.tool_receipts
            if r.tool == "check_promotions" and 200 <= r.status < 300
        ),
        None,
    )
    if not check:
        return None
    resp = check.response or {}
    if not resp.get("no_active_promo"):
        return None
    product = resp.get("product_name") or "that item"
    return (
        f"I checked, and there aren't any active promotions on the {product} right now — "
        f"the previous offer has expired, so it stays at full price. "
        f"I'll flag it if a new deal opens up. Anything else I can help with?"
    )


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
            declined = _render_promo_declined_reply(action_output)
            if declined:
                return declined
            blocked_discount = _render_blocked_discount_reply(action_output)
            if blocked_discount:
                return blocked_discount
            discount = _render_discount_reply(action_output)
            if discount:
                return discount
            no_promo = _render_no_promo_reply(action_output)
            if no_promo:
                return no_promo
            propose = _render_promo_propose_reply(action_output)
            if propose:
                return propose
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
