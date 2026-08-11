from re import U
import asyncio
import time
import random
from datetime import datetime
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from colorama import Fore, Style
from app.models.policy_output import PolicyOutput
from app.models.records_output import RecordsOutput
from app.models.action_output import ActionOutput, ToolReceipt
from app.models.order import Order
from app.toggles import ToggleManager
from app.promo_spike import discount_for_now
from app.rag.queries import find_catalog_product, get_product_promotions
from app.session_cache import recall_promo, remember_promo, clear_promo
from galileo import log

from agent_control import control, ControlViolationError, ControlSteerError


def _receipt_total_from_orders(orders: List[Any]) -> tuple[float | None, str | None, str | None]:
    """Compute (total_amount, order_id, currency) for the user's top order.

    Used by ``create_refund_request`` to surface the ground-truth
    receipt amount alongside whatever amount the agent ends up using, so the
    refund-compliance control can compare them.
    """
    if not orders:
        return None, None, None
    order = orders[0]

    def _g(attr: str, default: Any = None) -> Any:
        return getattr(order, attr, None) if hasattr(order, attr) else (
            order.get(attr, default) if isinstance(order, dict) else default
        )

    try:
        quantity = int(_g("quantity", 1) or 1)
        unit_price = float(_g("unit_price", 0.0) or 0.0)
    except (TypeError, ValueError):
        return None, _g("_id") or _g("id"), _g("currency")
    total = round(unit_price * quantity, 2)
    return total, _g("_id") or _g("id"), _g("currency")

# Intent classification constants
INTENT_REFUND_REQUEST = "refund_request"
INTENT_ORDER_INQUIRY = "order_inquiry"
INTENT_RECEIPT_REQUEST = "receipt_request"
INTENT_PROMO_INQUIRY = "promo_inquiry"
INTENT_GENERAL = "general"
VALID_INTENTS = [
    INTENT_REFUND_REQUEST,
    INTENT_ORDER_INQUIRY,
    INTENT_RECEIPT_REQUEST,
    INTENT_PROMO_INQUIRY,
    INTENT_GENERAL,
]

# Affirmations that, when a promo is already on the table (proposed on the
# previous turn), mean "yes, apply that discount." Kept keyword-based rather
# than LLM-classified because a bare "yes" carries no product signal for the
# intent classifier — the pending-promo context is what disambiguates it.
_AFFIRMATIVE_PREFIXES = (
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "go ahead", "go for it",
    "do it", "please do", "apply", "add it", "add to", "sounds good",
    "confirm", "absolutely", "let's do", "lets do", "y ",
)

# Verbs that mean the customer wants the promo applied *now*, in the same
# message they asked about it (single-turn). Used both by power users and by
# the traffic generator's single-shot scenarios.
_APPLY_NOW_KEYWORDS = (
    "apply", "add it", "add to cart", "add to my cart", "go ahead", "add the tv",
    "add the laptop", "put it in", "check out", "checkout",
)


def _is_affirmative(text: str) -> bool:
    t = (text or "").strip().lower().rstrip(".!,")
    if not t:
        return False
    if t in {"y", "yes", "yep", "yeah", "yup", "ok", "okay", "sure"}:
        return True
    return any(t.startswith(prefix) for prefix in _AFFIRMATIVE_PREFIXES)


def _wants_apply_now(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in _APPLY_NOW_KEYWORDS)


# Declines that, when a promo is on the table, mean "no, don't apply it." Used
# by the "No thanks" quick-reply chip so the agent bows out gracefully (clears
# the pending offer, no ticket) instead of falling through to generic handling.
_DECLINE_PREFIXES = (
    "no thanks", "no thank you", "no", "nope", "nah", "not now", "not right now",
    "maybe later", "don't", "dont", "do not", "pass", "skip", "cancel",
    "no thanks!", "leave it",
)


def _is_decline(text: str) -> bool:
    t = (text or "").strip().lower().rstrip(".!,")
    if not t:
        return False
    if t in {"n", "no", "nope", "nah", "pass", "skip", "cancel"}:
        return True
    return any(t.startswith(prefix) for prefix in _DECLINE_PREFIXES)


# Sentiment classification constants
SENTIMENT_NEGATIVE = "negative"
SENTIMENT_POSITIVE = "positive"
SENTIMENT_NEUTRAL = "neutral"
VALID_SENTIMENTS = [SENTIMENT_NEGATIVE, SENTIMENT_POSITIVE, SENTIMENT_NEUTRAL]



class ActionAgent:
    """A5: Action Agent - External API calls and tool execution"""
    
    def __init__(self):
        from app.llm.client import openai_client
        self.llm = openai_client.client
        self.available_tools = {
            "create_ticket": self._create_ticket,
            "update_ticket": self._update_ticket,
            "escalate_ticket": self._escalate_ticket,
            "create_refund_request": self._create_refund_request,
            "explain_refund_state": self._explain_refund_state,
            "explain_order_state": self._explain_order_state,
            "get_receipt": self._get_receipt,
            "check_promotions": self._check_promotions,
            "apply_discount": self._apply_discount,
        }
        self.toggles = ToggleManager()
        # Set per-request in process(); tools read it for the two-turn promo flow.
        self._chat_session_id: Optional[str] = None
    
    @log(span_type="agent", name="Process")
    async def process(self, 
                    user_id: str, 
                    user_query: str, 
                    policy_output: PolicyOutput, 
                    records_output: RecordsOutput,
                    chat_session_id: Optional[str] = None,
                    intent: Optional[str] = None) -> ActionOutput:

        # Anchor the two-turn promo flow to this chat session so the tools can
        # recall/remember the "promo in focus" across turns. None for the CLI /
        # traffic generator, which intentionally falls back to the spike schedule.
        self._chat_session_id = chat_session_id

        # "No thanks" on a pending promo: bow out cleanly — drop the offer and
        # return a decline resolution with no tools (no ticket, no LLM calls).
        # The synthesizer renders a polite decline for this resolution.
        if recall_promo(self._chat_session_id) and _is_decline(user_query):
            print(f"  {Fore.YELLOW}Customer declined the pending promo -> clearing offer{Style.RESET_ALL}")
            clear_promo(self._chat_session_id)
            return ActionOutput(
                resolution="promo_declined",
                tool_receipts=[],
                cost_token_usd=0.0,
            )

        # Records/Policy are skipped for the promo path (see the graph router),
        # so tolerate their outputs being None. The promo tools don't read them.
        tickets = records_output.tickets if records_output else []
        requests = records_output.requests if records_output else []
        # import pdb;pdb.set_trace()
        # Determine which tools to call
        # Extract existing sentiment from relevant tickets
        existing_sentiment = None

        if tickets:
            latest_ticket = tickets[0]  # Assuming sorted by date
            existing_sentiment = latest_ticket.customer_sentiment if hasattr(latest_ticket, 'customer_sentiment') else latest_ticket.get('customer_sentiment')

        print(f"  {Fore.YELLOW}Classifying sentiment via LLM...{Style.RESET_ALL}")
        latest_sentiment = await self._classify_sentiment(user_query)
        # latest_sentiment = await self._classify_sentiment_v2(user_query)
        print(f"  {Fore.YELLOW}Detected sentiment: {latest_sentiment}{Style.RESET_ALL}")

        if intent is None:
            print(f"  {Fore.YELLOW}Classifying intent via LLM...{Style.RESET_ALL}")
        else:
            print(f"  {Fore.YELLOW}Using intent from router: {intent}{Style.RESET_ALL}")
        tools_to_call = await self._determine_tools(user_query, user_id, policy_output, records_output, latest_sentiment, precomputed_intent=intent)
        print(f"  {Fore.YELLOW}Tools to execute: {', '.join(tools_to_call)}{Style.RESET_ALL}")

        tool_receipts: List[Dict[str, Any]] = []
        total_cost = 0.002  # Cost for LLM intent classification and sentiment analysis

        for tool_name in tools_to_call:
            if tool_name in self.available_tools:
                print(f"  {Fore.YELLOW}Executing tool: {tool_name}...{Style.RESET_ALL}")
                receipt = await self._execute_tool(tool_name, user_query, user_id, policy_output, records_output, latest_sentiment)
                status_icon = "✓" if 200 <= receipt.status < 300 else "✗"
                print(f"  {Fore.YELLOW}{status_icon} Tool {tool_name}: {receipt.status} ({receipt.latency_ms:.0f}ms){Style.RESET_ALL}")
                tool_receipts.append(receipt.dict())
                total_cost += self._calculate_tool_cost(tool_name)

                # Refund-compliance demo: when create_refund_request is blocked
                # by the control AND we have the receipt's ground-truth amount,
                # synthesize a follow-up "corrected" refund receipt so the UI
                # shows the "Refund issued" chip with the right amount. The
                # narrative: control caught the wrong amount, system retried
                # with the receipt total. The blocked receipt stays in the
                # list so the audit trail / Galileo trace still shows the
                # original (wrong) attempt and the deny event.
                if (
                    tool_name == "create_refund_request"
                    and receipt.status == 412
                    and (receipt.response or {}).get("error") == "blocked_by_agent_control"
                ):
                    blocked_response = receipt.response or {}
                    if blocked_response.get("receipt_amount") is not None:
                        corrected_start = time.time()
                        corrected_response = await self._issue_refund_at_receipt_amount(
                            user_query, user_id, blocked_response,
                        )
                        corrected_latency = (time.time() - corrected_start) * 1000
                        print(
                            f"  {Fore.GREEN}↩ Re-issued refund at receipt amount "
                            f"{corrected_response.get('currency')} "
                            f"{corrected_response.get('amount')} (control-corrected)"
                            f"{Style.RESET_ALL}"
                        )
                        corrected_receipt = ToolReceipt(
                            tool="create_refund_request",
                            status=corrected_response.get("status", 201),
                            latency_ms=corrected_latency,
                            response=corrected_response,
                        )
                        tool_receipts.append(corrected_receipt.dict())
                        total_cost += self._calculate_tool_cost("create_refund_request")

        resolution = self._determine_resolution([ToolReceipt(**r) for r in tool_receipts], records_output)
        print(f"  {Fore.YELLOW}Final resolution: {resolution}{Style.RESET_ALL}")
        
        return ActionOutput(
            resolution=resolution,
            tool_receipts=[ToolReceipt(**r) for r in tool_receipts],
            cost_token_usd=total_cost,
        )
    
    @log(span_type="agent", name="Classify Route")
    async def classify_route(self, user_query: str, chat_session_id: Optional[str]) -> tuple[str, str]:
        """Decide the graph route (``"promo"`` vs ``"support"``) and return the
        classified intent alongside it.

        Lets the graph skip the Records/Policy agents (and their irrelevant tool
        calls) for the promo demo while leaving the refund/order/receipt path
        untouched. The intent is threaded into ``process`` so it isn't
        re-classified downstream.

        Turn 2 of the two-turn promo flow ("yes") has no promo keywords, so the
        pending-promo check (same rule ``_determine_tools`` uses) routes it to
        the promo path before falling back to the LLM classifier.
        """
        self._chat_session_id = chat_session_id
        pending_promo = recall_promo(chat_session_id)
        # Turn 2 "yes"/"apply" or "no thanks" both stay on the lean promo path
        # (no records/policy) so accepting or declining the offer is clean.
        if pending_promo and (_is_affirmative(user_query) or _is_decline(user_query)):
            return "promo", INTENT_PROMO_INQUIRY

        intent = await self._classify_intent(user_query, {"policy": None, "records": None})
        route = "promo" if intent == INTENT_PROMO_INQUIRY else "support"
        return route, intent

    @log(span_type="agent", name="Determine Tools")
    async def _determine_tools(self, 
                            user_query: str, 
                            user_id: str, 
                            policy_output: PolicyOutput, 
                            records_output: RecordsOutput, 
                            latest_sentiment: str,
                            precomputed_intent: Optional[str] = None) -> List[str]:
        """Determine which tools to call based on context"""
        tools = []

        # --- Two-turn promo flow -------------------------------------------
        # Turn 2: a promo was proposed last turn (pending in the session) and
        # the customer just said "yes" / "apply it". Skip re-checking and go
        # straight to applying the exact offer we put on the table. Kept ahead
        # of intent classification because a bare "yes" has no promo signal.
        pending_promo = recall_promo(self._chat_session_id)
        if pending_promo and _is_affirmative(user_query):
            print(f"  {Fore.YELLOW}Pending promo confirmed by customer -> apply_discount{Style.RESET_ALL}")
            return ["apply_discount"]

        # Reuse the router's classification when provided so we don't spend a
        # second LLM call (and second "Classify Intent" span) per turn.
        intent = precomputed_intent if precomputed_intent is not None else await self._classify_intent(
            user_query, 
            {"policy": policy_output, "records": records_output}
        )

        # Turn 1 (or single-turn): customer is shopping for a deal. Propose the
        # promo (check only) and wait for confirmation. If they explicitly asked
        # to apply it in the same breath ("...and add it to my cart"), do both
        # now. The traffic generator hits this single-turn path.
        if intent == INTENT_PROMO_INQUIRY:
            if _wants_apply_now(user_query):
                return ["check_promotions", "apply_discount"]
            return ["check_promotions"]

        existing_ticket = self._find_existing_ticket(records_output.tickets, user_id)
        
        # Create or update ticket for any request
        if existing_ticket:
            tools.append("update_ticket")
        else:
            tools.append("create_ticket")
        # Handle ticket escalation for extremely negative sentiment
        if latest_sentiment == SENTIMENT_NEGATIVE:
            tools.append("escalate_ticket")
        
        # Handle refund requests
        if intent == INTENT_REFUND_REQUEST:
            tools.append("create_refund_request")
            tools.append("explain_refund_state")

        if intent == INTENT_ORDER_INQUIRY:
            tools.append("explain_order_state")

        # "Show me the receipt for X" — surface the order details as a
        # structured receipt. Used in the refund-compliance demo: customer
        # asks for the receipt first, then asks for a refund, and we want to
        # show that the refund amount doesn't match the receipt amount.
        if intent == INTENT_RECEIPT_REQUEST:
            tools.append("get_receipt")

        return tools
    
    @log(span_type="agent", name="Classify Intent")
    async def _classify_intent(self, text: str, context: Dict[str, Any]) -> str:

        """Classify user intent using LLM"""
        prompt = f"""
        Classify the following customer message into one of these intents:
        - {INTENT_REFUND_REQUEST}: Customer wants a refund, return, or money back
        - {INTENT_ORDER_INQUIRY}: Customer asking about order status, delivery, shipping
        - {INTENT_RECEIPT_REQUEST}: Customer wants to see the receipt, invoice, or purchase details for an order (e.g. "show me the receipt", "what did I pay", "send me the invoice", "show purchase details")
        - {INTENT_PROMO_INQUIRY}: Customer is asking whether a discount, deal, promo, coupon, or sale is available on an item they want to buy, and/or wants that discount applied (e.g. "is there a discount on the OLED TV?", "any promo running on the laptop?", "apply the deal and add it to my cart")
        - {INTENT_GENERAL}: Any other customer service request

        Important rules:
        - If the customer is explicitly asking to return, refund, or get money back for a product, classify as {INTENT_REFUND_REQUEST} — even when other unrelated prior refund records exist in their history.
        - Only classify as {INTENT_ORDER_INQUIRY} when a refund request already exists for the SAME product the customer is asking about right now (same product name / SKU). Prior refunds for *different* products do not count.
        - Classify as {INTENT_PROMO_INQUIRY} when the customer is shopping and asks about a discount/promo/deal/sale/coupon on an item, or asks to apply such a discount. This is about buying a NEW item, not returning an existing order.

        Customer message: "{text}"
        Existing context: "{context}"

        Respond with only the intent name ({INTENT_REFUND_REQUEST}, {INTENT_ORDER_INQUIRY}, {INTENT_RECEIPT_REQUEST}, {INTENT_PROMO_INQUIRY}, or {INTENT_GENERAL}):
        """
        
        try:
            response = await self.llm.complete(prompt)
            intent = response.strip().lower()
            
            # Validate response
            return intent if intent in VALID_INTENTS else INTENT_GENERAL
        except Exception as e:
            print(f"  Intent classification failed: {e}")
            return INTENT_GENERAL
    
    @log(span_type="agent", name="Classify Sentiment")
    async def _classify_sentiment(self, text: str) -> str:
        """Classify customer sentiment using LLM based on current text and existing sentiment"""
        
        prompt = f"""
        Analyze the customer's sentiment based on their current message.
        Current customer message: "{text}"
        
        Classify the overall sentiment as one of:
        - {SENTIMENT_NEGATIVE}: Customer is angry, frustrated, upset, or expressing dissatisfaction
        - {SENTIMENT_POSITIVE}: Customer is happy, satisfied, grateful, or expressing appreciation
        - {SENTIMENT_NEUTRAL}: Customer is calm, matter-of-fact, or neither positive nor negative
        
        Consider both the current message and any escalation in sentiment from previous interactions.
        
        Respond with only the sentiment: {SENTIMENT_NEGATIVE}, {SENTIMENT_POSITIVE}, or {SENTIMENT_NEUTRAL}
        """
        
        try:
            response = await self.llm.complete(prompt)
            sentiment = response.strip().lower()
            
            # Validate response
            return sentiment if sentiment in VALID_SENTIMENTS else SENTIMENT_NEUTRAL
        except Exception as e:
            print(f"  Sentiment classification failed: {e}")
            return SENTIMENT_NEUTRAL

    @log(span_type="agent", name="Classify Sentiment")
    async def _classify_sentiment_v2(self, text: str) -> str:
        """Classify customer sentiment using LLM based on current text and existing sentiment"""
        
        prompt = f"""
        SYSTEM:
        You are a strict classifier for customer-service escalation SEVERITY, not generic sentiment.
        Follow the decision procedure exactly.

        DECISION PROCEDURE (apply in order):
        1) If the message contains any of: profanity, personal insults, slurs, threats, ALL-CAPS SHOUTING (≥50% of words uppercased), or repeated exclamation (e.g., "!!!"), classify as NEGATIVE.
        2) Else if the message expresses clear praise, gratitude, or happiness, classify as POSITIVE.
        3) Otherwise classify as NEUTRAL, including calm complaints, dissatisfaction, returns, or refund requests.

        OUTPUT:
        Return ONE token only: negative | positive | neutral (lowercase).

        EXAMPLES:
        - "THIS SUCKS YOU SUCK EVERYONE SUCKS HOW DARE YOU" -> negative
        - "I need a refund for my bluetooth electronics purchase, I don't like the product" -> neutral
        - "I really didn't like the product, I'm returning it" -> neutral
        - "I'm not happy with my speaker system, the sound quality is not what I expected" -> neutral
        - "Thanks so much for the quick replacement!" -> positive

        MESSAGE:
        {text}
        """
        
        try:
            response = await self.llm.complete(prompt)
            sentiment = response.strip().lower()
            
            # Validate response
            return sentiment if sentiment in VALID_SENTIMENTS else SENTIMENT_NEUTRAL
        except Exception as e:
            print(f"  Sentiment classification failed: {e}")
            return SENTIMENT_NEUTRAL


    ## TOOLS ##
    async def _execute_tool(self, tool_name: str, user_query: str, user_id: str, policy_output: PolicyOutput, records_output: RecordsOutput, latest_sentiment: str) -> ToolReceipt:
        """Execute a specific tool"""
        tool_start = time.time()
        
        try:
            tool_func = self.available_tools[tool_name]
            response = await tool_func(user_query, user_id, policy_output, records_output, latest_sentiment)
            
            latency = (time.time() - tool_start) * 1000
            
            return ToolReceipt(
                tool=tool_name,
                status=response.get("status", 200),
                latency_ms=latency,
                response=response
            )
        except ControlViolationError as e:
            # Agent Control denied this tool call. Surface it as a 4xx receipt
            # so the rest of the workflow can keep going (audit + reply still
            # run) and the operator can see *why* it was blocked.
            #
            # NOTE: This is intentionally redundant with the inline catch in
            # _create_refund_request. We catch here too because the @control
            # decorator on the tool raises BEFORE @log sees a return value,
            # which would make the Galileo tool span show an exception instead
            # of the structured block payload. The inline catch in each tool
            # is what fixes the Galileo span; this outer catch is the safety
            # net for any tool that gets @control'd later without remembering
            # the inline wrapper pattern.
            #
            # TODO: Remove both catches once Enterprise Agent Control ships
            # native span instrumentation that auto-logs deny outcomes as
            # structured tool outputs (rather than raising through user code).
            latency = (time.time() - tool_start) * 1000
            print(
                f"  {Fore.RED}🚫 Tool {tool_name} blocked by control "
                f"'{getattr(e, 'control_name', 'unknown')}': {e}{Style.RESET_ALL}"
            )
            return ToolReceipt(
                tool=tool_name,
                status=412,  # Precondition Failed -- the control's precondition
                latency_ms=latency,
                response={
                    "error": "blocked_by_agent_control",
                    "control_name": getattr(e, "control_name", None),
                    "message": str(e),
                    "metadata": getattr(e, "metadata", None),
                },
            )
        except Exception as e:
            latency = (time.time() - tool_start) * 1000
            import traceback
            print(
                f"  {Fore.RED}✗ Tool {tool_name} raised {type(e).__name__}: {e}{Style.RESET_ALL}"
            )
            traceback.print_exc()
            return ToolReceipt(
                tool=tool_name,
                status=500,
                latency_ms=latency,
                response={"error": str(e), "exception_type": type(e).__name__}
            )

    @log(span_type="tool", name="Create Refund Request")
    async def _create_refund_request(self, user_query: str, user_id: str, policy_output: PolicyOutput, records_output: RecordsOutput, latest_sentiment: str) -> Dict[str, Any]:
        """Simulate creating a new refund request.

        The actual refund logic lives in ``create_refund_request``,
        which is decorated with ``@control``. We catch ``ControlViolationError``
        here so Galileo's ``@log`` span sees a normal return value describing
        the block, rather than an exception. The shape mirrors what
        ``_execute_tool`` would emit, so the frontend renders it the same way.

        Why the two-function split: decorator order forces a tradeoff. If
        ``@control`` is outside ``@log``, the tool span never records the
        block (control raises first). If ``@control`` is inside ``@log``,
        the span records the block but as an exception, not as a structured
        output. Splitting lets ``@log`` wrap a function that always returns
        cleanly — block or success — so the Galileo trace tells the full
        story.

        TODO: Collapse back to a single decorated function once Enterprise
        Agent Control ships native span instrumentation that emits deny
        outcomes as structured tool outputs directly.
        """
        try:
            return await self.create_refund_request(
                user_query, user_id, policy_output, records_output, latest_sentiment,
            )
        except ControlViolationError as e:
            print(
                f"  {Fore.RED}🚫 create_refund_request blocked by control "
                f"'{getattr(e, 'control_name', 'unknown')}': {e}{Style.RESET_ALL}"
            )
            # Enrich the blocked payload with the receipt's ground-truth
            # amount/product so the synthesizer can render a clean
            # "refund processed for $X" reply (the demo narrative is that
            # the control quietly corrected the amount).
            receipt_amount, receipt_order_id, receipt_currency = _receipt_total_from_orders(
                records_output.orders
            )
            product_name: Optional[str] = None
            if records_output.orders:
                top = records_output.orders[0]
                product_name = (
                    getattr(top, "product_name", None)
                    if hasattr(top, "product_name")
                    else (top.get("product_name") if isinstance(top, dict) else None)
                )
            return {
                "status": 412,
                "error": "blocked_by_agent_control",
                "control_name": getattr(e, "control_name", None),
                "message": str(e),
                "metadata": getattr(e, "metadata", None),
                "status_message": f"Blocked by Agent Control: {e}",
                "receipt_amount": receipt_amount,
                "receipt_order_id": receipt_order_id,
                "currency": receipt_currency or "USD",
                "product_name": product_name,
            }

    @log(span_type="tool", name="Issue Refund (Corrected)")
    async def _issue_refund_at_receipt_amount(
        self,
        user_query: str,
        user_id: str,
        blocked_response: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Real follow-up refund call invoked when the primary
        ``create_refund_request`` is blocked by the refund-compliance control.

        Notes:
        - Intentionally NOT decorated with ``@control``: this is the
          remediation path that runs after the control has already vetted
          the receipt amount. Re-evaluating would just deny again because
          the same control logic is keyed on the prior call's metadata.
        - Decorated with ``@log`` so the Galileo trace shows a distinct
          "Issue Refund (Corrected)" span next to the denied
          "Create Refund Request" span — the audit trail tells the full
          remediation story.
        - In production this would also persist to the refund collection;
          for the demo we simulate latency and return the structured
          receipt payload that the frontend chip + synthesizer key off of.
        """
        time.sleep(random.uniform(0.05, 0.15))

        receipt_amount = blocked_response.get("receipt_amount")
        currency = blocked_response.get("currency") or "USD"
        order_id = blocked_response.get("receipt_order_id")
        product_name = blocked_response.get("product_name")

        return {
            "status": 201,
            "refund_request_id": f"RR_{random.randint(10000, 99999)}",
            "user_id": user_id,
            "amount": receipt_amount,
            "currency": currency,
            "description": user_query[:200],
            "refund_status": "approved",
            "status_message": "Refund issued at receipt amount (control-corrected)",
            "receipt_amount": receipt_amount,
            "receipt_order_id": order_id,
            "product_name": product_name,
            "amount_matches_receipt": True,
            "control_corrected": True,
            "original_blocked_by": blocked_response.get("control_name"),
        }

    @control()
    async def create_refund_request(self, user_query: str, user_id: str, policy_output: PolicyOutput, records_output: RecordsOutput, latest_sentiment: str) -> Dict[str, Any]:
        """Refund logic guarded by Agent Control. Do not call directly — go
        through ``_create_refund_request`` so the block path is logged cleanly.

        Known bug (intentional, demonstrated by the refund-compliance control):
        the agent reads the refund amount from the user's most recent prior
        refund record (``records_output.requests[0]``) instead of computing it
        from the order being refunded. When the customer asks to refund a
        recent order whose total differs from any prior refund they had, the
        agent reports the wrong amount. The ``refund-compliance`` control on
        the AC server flips ``amount_matches_receipt`` to the trigger value
        and denies the call.
        """
        time.sleep(random.uniform(0.05, 0.15))

        amount = 0.0
        currency = "USD"

        if records_output.requests:
            latest_request = records_output.requests[0]
            amount = latest_request.amount if hasattr(latest_request, 'amount') else latest_request.get('amount', 0.0)
            currency = latest_request.currency if hasattr(latest_request, 'currency') else latest_request.get('currency', 'USD')

        receipt_amount, receipt_order_id, receipt_currency = _receipt_total_from_orders(
            records_output.orders
        )
        if receipt_currency:
            currency = receipt_currency

        # Float equality with a small tolerance so we don't false-positive on
        # rounding noise. The control evaluator only sees the boolean.
        amount_matches_receipt = (
            receipt_amount is not None
            and abs(float(amount) - float(receipt_amount)) < 0.01
        )

        return {
            "status": 201,
            "refund_request_id": f"RR_{random.randint(10000, 99999)}",
            "user_id": user_id,
            "amount": amount,
            "currency": currency,
            "description": user_query[:200],
            "refund_status": "investigation",
            "status_message": "Refund request created",
            # ---- refund-compliance signals ----
            "receipt_amount": receipt_amount,
            "receipt_order_id": receipt_order_id,
            "amount_matches_receipt": amount_matches_receipt,
        }

    @log(span_type="tool", name="Get Receipt")
    async def _get_receipt(self, user_query: str, user_id: str, policy_output: PolicyOutput, records_output: RecordsOutput, latest_sentiment: str) -> Dict[str, Any]:
        """Return a detailed receipt for the user's most relevant order.

        Used in the refund-compliance demo: the customer asks for a receipt
        for a recent purchase, then asks for a refund — making it obvious to
        anyone watching the demo that the refund amount the agent later
        produces doesn't match the receipt total.
        """
        time.sleep(random.uniform(0.05, 0.15))
        orders = records_output.orders

        if not orders:
            return {
                "status": 404,
                "error": "no_order_found",
                "status_message": (
                    f"No order found for this customer matching '{user_query[:80]}'."
                ),
            }

        order = orders[0]

        def _g(attr: str, default: Any = None) -> Any:
            return getattr(order, attr, None) if hasattr(order, attr) else (
                order.get(attr, default) if isinstance(order, dict) else default
            )

        order_id = _g("_id") or _g("id")
        product_name = _g("product_name", "unknown")
        sku = _g("sku", "unknown")
        quantity = int(_g("quantity", 1) or 1)
        unit_price = float(_g("unit_price", 0.0) or 0.0)
        currency = _g("currency", "USD")
        order_date = _g("order_date")
        shipping_address = _g("shipping_address", {}) or {}
        status = _g("status", "unknown")

        total_amount = round(unit_price * quantity, 2)

        return {
            "status": 200,
            "order_id": order_id,
            "product_name": product_name,
            "sku": sku,
            "quantity": quantity,
            "unit_price": unit_price,
            "total_amount": total_amount,
            "currency": currency,
            "order_date": order_date.isoformat() if hasattr(order_date, "isoformat") else order_date,
            "shipping_address": shipping_address,
            "order_status": status,
            "status_message": "Receipt retrieved",
        }

    @log(span_type="tool", name="Check Promotions")
    async def _check_promotions(self, user_query: str, user_id: str, policy_output: PolicyOutput, records_output: RecordsOutput, latest_sentiment: str) -> Dict[str, Any]:
        """Look up promotions for the item the customer is asking about.

        Reads promos from a stale cache (``get_product_promotions`` does NOT
        filter on ``effective_until``), so expired offers come back looking
        live. This is the root-cause step the demo showcases: the data the
        agent reasons over already bypasses the promo end date.
        """
        time.sleep(random.uniform(0.05, 0.15))

        product = await find_catalog_product(user_query)
        if not product:
            return {
                "status": 404,
                "error": "no_product_found",
                "status_message": (
                    f"Couldn't match '{user_query[:80]}' to a catalog product."
                ),
            }

        sku = product.get("sku")
        list_price = float(product.get("unit_price", 0.0) or 0.0)
        currency = product.get("currency", "USD")
        promos = await get_product_promotions(sku) or []

        now = datetime.utcnow()

        def _parse_dt(value: Any) -> Optional[datetime]:
            if isinstance(value, datetime):
                return value
            if isinstance(value, str):
                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
                except ValueError:
                    return None
            return None

        def _discount_usd(discount_type: Any, discount_value: Any) -> float:
            try:
                value = float(discount_value or 0.0)
            except (TypeError, ValueError):
                return 0.0
            if str(discount_type).lower() in ("percent", "percentage", "pct"):
                return round(list_price * value, 2)
            return round(value, 2)

        promotions: List[Dict[str, Any]] = []
        for promo in promos:
            end = _parse_dt(promo.get("effective_until"))
            expired = end is not None and end < now
            promotions.append({
                "code": promo.get("code"),
                "description": promo.get("description"),
                "discount_type": promo.get("discount_type"),
                "discount_value": promo.get("discount_value"),
                "tier": promo.get("tier"),
                "effective_until": end.isoformat() if end else None,
                "expired": expired,
                "discount_usd": _discount_usd(promo.get("discount_type"), promo.get("discount_value")),
            })

        has_expired_promo = any(p["expired"] for p in promotions)

        # Pick the promo to put on the table: the biggest dollar discount. In
        # the seeded catalog that's the *expired* clearance blowout — exactly
        # the stale offer we want the agent to surface (and Agent Control to
        # later block). Live promos exist too, but they're smaller, so the
        # "best deal" the agent proposes is the one that already bypassed its
        # end date.
        proposed = max(promotions, key=lambda p: p["discount_usd"], default=None)

        result: Dict[str, Any] = {
            "status": 200,
            "product_name": product.get("product_name"),
            "sku": sku,
            "list_price": list_price,
            "currency": currency,
            "promotions": promotions,
            "has_expired_promo": has_expired_promo,
            "status_message": (
                f"Found {len(promotions)} promotion(s) for {product.get('product_name')}"
            ),
        }

        # Catch the stale offer *at proposal time*, before we pitch it to the
        # customer. The guard step exposes ``proposed_promo_expired`` so a
        # ``steer`` control keyed on it fires here (turn 1) rather than only at
        # apply_discount (turn 2). On steer we honor the promo's end date:
        # re-pick the best *live* promo, or drop the proposal entirely.
        if proposed:
            try:
                await self._promo_proposal_guard(
                    product_name=product.get("product_name"),
                    promo_code=proposed["code"],
                    proposed_promo_expired=bool(proposed["expired"]),
                    proposed_promo_end_date=proposed["effective_until"],
                    proposed_discount_usd=float(proposed["discount_usd"]),
                )
            except ControlSteerError as exc:
                print(
                    f"  {Fore.YELLOW}↩ Promo proposal steered by Agent Control "
                    f"(best deal {proposed['code']} expired {proposed['effective_until']}); "
                    f"re-checking live offers only{Style.RESET_ALL}"
                )
                live = [p for p in promotions if not p["expired"]]
                proposed = max(live, key=lambda p: p["discount_usd"], default=None)
                result["steered_by_agent_control"] = True
                result["control_message"] = str(exc)

        if proposed:
            proposed_discount = float(proposed["discount_usd"])
            result.update({
                "proposed_promo_code": proposed["code"],
                "proposed_promo_description": proposed["description"],
                "proposed_discount_usd": proposed_discount,
                "proposed_final_price": round(max(list_price - proposed_discount, 0.0), 2),
                "proposed_promo_expired": proposed["expired"],
                "proposed_promo_end_date": proposed["effective_until"],
                "proposed_discount_tier": proposed["tier"],
            })

            # Stash the offer so a follow-up "yes" applies this exact promo.
            # No-op when there's no chat session (CLI/traffic generator).
            remember_promo(self._chat_session_id, {
                "product_name": product.get("product_name"),
                "sku": sku,
                "currency": currency,
                "list_price": list_price,
                "discount_usd": proposed_discount,
                "promo_code": proposed["code"],
                "promo_description": proposed["description"],
                "promo_end_date": proposed["effective_until"],
                "promo_expired": bool(proposed["expired"]),
                "discount_tier": proposed["tier"],
            })
        else:
            # No promo to put on the table: either none seeded, or the control
            # steered us away from the only (expired) offer. Clear any stale
            # pending promo so a later "yes" can't resurrect it, and flag the
            # "no active promo" case so the synthesizer says so plainly.
            clear_promo(self._chat_session_id)
            if result.get("steered_by_agent_control"):
                result["no_active_promo"] = True
                result["status_message"] = (
                    f"No active promotions available for {product.get('product_name')}"
                )

        return result

    @control(step_name="check_promotions")
    async def _promo_proposal_guard(
        self,
        product_name: str,
        promo_code: str,
        proposed_promo_expired: bool,
        proposed_promo_end_date: Optional[str],
        proposed_discount_usd: float,
    ) -> Dict[str, Any]:
        """Guarded checkpoint for the promo *proposal* (turn 1).

        Does no real work — it just echoes the proposal signals as its output so
        Agent Control can evaluate them. A ``steer`` control scoped to step name
        ``check_promotions`` (path ``output``, ``proposed_promo_expired`` must be
        ``false``) fires when the best deal is past its end date, raising
        ``ControlSteerError``; ``_check_promotions`` catches it and re-checks the
        live offers. Registered as an ``llm`` step, so at the POST stage the
        server sees this dict as ``output``.
        """
        return {
            "product_name": product_name,
            "promo_code": promo_code,
            "proposed_promo_expired": bool(proposed_promo_expired),
            "proposed_promo_end_date": proposed_promo_end_date,
            "proposed_discount_usd": float(proposed_discount_usd),
        }

    async def _apply_discount(self, user_query: str, user_id: str, policy_output: PolicyOutput, records_output: RecordsOutput, latest_sentiment: str) -> Dict[str, Any]:
        """Apply a promo to the item and add it to the customer's cart.

        Resolves *which* promo to apply from two sources:

        * Interactive UI (a chat session exists): the exact promo we proposed
          earlier this session — recalled from the session cache — so the
          customer gets the deal they just said "yes" to (the real ~55%
          clearance value, drastic on purpose).
        * CLI / traffic generator (no chat session): the time-based spike
          schedule (``discount_for_now``), which ramps the discount over the
          run so the Galileo trace shows a normal→spike pattern.

        Either way the applied promo is expired — that's the leak the demo
        catches. Delegates to ``_apply_discount_span`` so the tool span carries
        the discount dollars as metadata and the ``@control`` guard can block it.
        """
        pending = recall_promo(self._chat_session_id)

        if pending:
            resolved = dict(pending)
        else:
            product = await find_catalog_product(user_query)
            if not product:
                return {
                    "status": 404,
                    "error": "no_product_found",
                    "status_message": (
                        f"Couldn't match '{user_query[:80]}' to a catalog product."
                    ),
                }
            list_price = float(product.get("unit_price", 0.0) or 0.0)
            schedule = discount_for_now(list_price)
            resolved = {
                "product_name": product.get("product_name"),
                "sku": product.get("sku"),
                "currency": product.get("currency", "USD"),
                "list_price": list_price,
                "discount_usd": schedule["discount_usd"],
                "promo_code": schedule["promo_code"],
                "promo_description": schedule["promo_description"],
                "promo_end_date": schedule["promo_end_date"].isoformat(),
                "promo_expired": schedule["promo_expired"],
                "discount_tier": schedule["tier"],
            }

        try:
            return await self._apply_discount_span(
                product_name=resolved.get("product_name"),
                sku=resolved.get("sku"),
                currency=resolved.get("currency", "USD"),
                list_price=float(resolved.get("list_price", 0.0) or 0.0),
                discount_usd=float(resolved.get("discount_usd", 0.0) or 0.0),
                promo_code=resolved.get("promo_code"),
                promo_description=resolved.get("promo_description"),
                promo_end_date=resolved.get("promo_end_date"),
                promo_expired=bool(resolved.get("promo_expired", False)),
                discount_tier=resolved.get("discount_tier"),
            )
        finally:
            # Whether applied or blocked, the offer has been acted on — forget it
            # so a later stray "yes" doesn't silently re-apply it.
            clear_promo(self._chat_session_id)

    @log(
        span_type="tool",
        name="Apply Discount",
        # Surface the applied discount as span metadata so it's visible (and
        # chartable over time) in the Galileo trace view. `params` callables
        # receive this function's merged input args, so the values below are
        # exactly what we attempted to apply. Metadata values must be strings.
        params={
            "metadata": lambda i: {
                "discount_usd": f"{float(i.get('discount_usd', 0.0)):.2f}",
                "list_price": f"{float(i.get('list_price', 0.0)):.2f}",
                "promo_code": str(i.get("promo_code", "")),
                "promo_expired": str(i.get("promo_expired", False)).lower(),
                "promo_end_date": str(i.get("promo_end_date", "")),
                "discount_tier": str(i.get("discount_tier", "")),
            }
        },
    )
    async def _apply_discount_span(
        self,
        product_name: str,
        sku: str,
        currency: str,
        list_price: float,
        discount_usd: float,
        promo_code: str,
        promo_description: str,
        promo_end_date: str,
        promo_expired: bool,
        discount_tier: str,
    ) -> Dict[str, Any]:
        """Run the guarded apply and translate a control block into a
        structured "expired, not applied" payload.

        Mirrors ``_create_refund_request``: the ``@control``-decorated
        ``apply_discount`` does the real work; if Agent Control denies it
        (promo past its end date), we catch the violation here and return a
        412 that keeps the customer at full price. Catching inside this span
        keeps the Galileo trace clean — the block shows up as the span's output
        plus the deny event, not an unhandled exception — while the metadata
        above still records what the agent *tried* to give away.
        """
        try:
            return await self.apply_discount(
                product_name,
                sku,
                currency,
                list_price,
                discount_usd,
                promo_code,
                promo_description,
                promo_end_date,
                promo_expired,
                discount_tier,
            )
        except ControlViolationError as exc:
            print(
                f"  {Fore.RED}⛔ Apply-discount blocked by Agent Control "
                f"(promo {promo_code} expired {promo_end_date}); keeping full price"
                f"{Style.RESET_ALL}"
            )
            return {
                "status": 412,
                "error": "blocked_by_agent_control",
                "control_message": str(exc),
                "product_name": product_name,
                "sku": sku,
                "currency": currency,
                "list_price": round(float(list_price), 2),
                # Nothing applied: the customer stays at list price.
                "discount_usd": 0.0,
                "final_price": round(float(list_price), 2),
                # What the agent *attempted* — surfaced so the UI/trace can show
                # the loss that was prevented.
                "attempted_discount_usd": round(float(discount_usd), 2),
                "attempted_final_price": round(max(float(list_price) - float(discount_usd), 0.0), 2),
                "promo_code": promo_code,
                "promo_description": promo_description,
                "promo_end_date": promo_end_date,
                "promo_expired": True,
                "discount_tier": discount_tier,
                "status_message": (
                    f"Blocked by Agent Control: promo {promo_code} expired "
                    f"{promo_end_date}; kept {currency} {round(float(list_price), 2)} full price"
                ),
            }

    @control()
    async def apply_discount(
        self,
        product_name: str,
        sku: str,
        currency: str,
        list_price: float,
        discount_usd: float,
        promo_code: str,
        promo_description: str,
        promo_end_date: str,
        promo_expired: bool,
        discount_tier: str,
    ) -> Dict[str, Any]:
        """Persist-and-return the discounted cart line (simulated).

        Guarded by Agent Control. The ``promo_expired`` flag in the return value
        is the signal the ``promo-compliance`` control keys on: when a control
        bound to this step decides the offer is stale, it raises
        ``ControlViolationError`` and this apply never lands. With no promo
        control configured (the default until the console is set up), the guard
        is a no-op and the expired discount goes through — the failure mode.
        """
        time.sleep(random.uniform(0.05, 0.15))

        final_price = round(max(float(list_price) - float(discount_usd), 0.0), 2)

        return {
            "status": 201,
            "cart_id": f"CART_{random.randint(10000, 99999)}",
            "product_name": product_name,
            "sku": sku,
            "currency": currency,
            "list_price": round(float(list_price), 2),
            "discount_usd": round(float(discount_usd), 2),
            "final_price": final_price,
            "promo_code": promo_code,
            "promo_description": promo_description,
            "promo_end_date": promo_end_date,
            # ---- expired-promo signals (what Galileo Signals/Evals/Control key on) ----
            "promo_expired": promo_expired,
            "discount_tier": discount_tier,
            "status_message": (
                f"Applied {promo_code} (-{currency} {round(float(discount_usd), 2)}) "
                f"and added {product_name} to cart"
            ),
        }

    @log(span_type="tool", name="Create Ticket")
    async def _create_ticket(self, user_query: str, user_id: str, policy_output: PolicyOutput, records_output: RecordsOutput, latest_sentiment: str) -> Dict[str, Any]:
        """Simulate creating a new support ticket"""
        time.sleep(random.uniform(0.05, 0.2))
        return {
            "status": 201,
            "ticket_id": f"TKT_{random.randint(10000, 99999)}",
            "user_id": user_id,
            "title": "Customer Request",
            "description": user_query[:280],
            "customer_sentiment": latest_sentiment,
            "comments": {f"{time.strftime('%Y-%m-%d %H:%M:%S')}": "AI Ops Desk creating ticket"},
            "status_message": "Ticket created"
        }

    @log(span_type="tool", name="Update Ticket")
    async def _update_ticket(self, user_query: str, user_id: str, policy_output: PolicyOutput, records_output: RecordsOutput, latest_sentiment: str) -> Dict[str, Any]:
        """Simulate updating an existing support ticket"""
        time.sleep(random.uniform(0.05, 0.15))
        existing_ticket = self._find_existing_ticket(records_output.tickets, user_id)
        ticket_id = existing_ticket._id if existing_ticket and hasattr(existing_ticket, '_id') else (existing_ticket.get('_id') if existing_ticket else f"TKT_{random.randint(10000, 99999)}")
        return {
            "status": 200,
            "ticket_id": ticket_id,
            "customer_sentiment": latest_sentiment,
            "comments": {f"{time.strftime('%Y-%m-%d %H:%M:%S')}": "AI Ops Desk updating ticket"},
            "status_message": "Ticket updated"
        }

    @log(span_type="tool", name="Escalate Ticket")
    async def _escalate_ticket(self, user_query: str, user_id: str, policy_output: PolicyOutput, records_output: RecordsOutput, latest_sentiment: str) -> Dict[str, Any]:
        """Simulate ticket escalation"""
        time.sleep(random.uniform(0.1, 0.3))
        
        return {
            "status": 200,
            "ticket_id": f"TKT_{random.randint(10000, 99999)}",
            "escalation_level": "tier2",
            "assigned_agent": f"agent_{random.randint(100, 999)}",
            "escalation_reason": f"Negative sentiment detected: {user_query[:100]}",
            "status_message": "Ticket escalated to tier 2 support"
        }
    
    @log(span_type="tool", name="Explain Refund State")
    async def _explain_refund_state(self, user_query: str, user_id: str, policy_output: PolicyOutput, records_output: RecordsOutput, latest_sentiment: str) -> Dict[str, Any]:
        """Explain the current state of refund requests"""
        time.sleep(random.uniform(0.05, 0.1))
        requests = records_output.requests
        
        if not requests:
            explanation = f"Based on your inquiry '{user_query[:50]}...', no refund requests found for this user."
        else:
            latest_request = requests[0]  # Assuming sorted by date
            status = latest_request.status if hasattr(latest_request, 'status') else latest_request.get("status", "unknown")
            amount = latest_request.amount if hasattr(latest_request, 'amount') else latest_request.get("amount", "unknown")
            currency = latest_request.currency if hasattr(latest_request, 'currency') else latest_request.get("currency", "USD")
            
            status_explanations = {
                "investigation": "Your refund request is currently under investigation by our team.",
                "refund in progress": "Your refund is being processed and will be completed soon.",
                "paid": "Your refund has been successfully processed and paid.",
                "closed": "This refund request has been closed.",
                "cancelled": "This refund request has been cancelled."
            }
            
            explanation = f"Regarding your inquiry: {user_query[:100]}... "
            explanation += f"Refund Request Status: {status_explanations.get(status, f'Status: {status}')}. "
            explanation += f"Amount: {currency} {amount}."
        
        return {
            "status": 200,
            "explanation": explanation,
            "status_message": "Refund state explained"
        }
    
    @log(span_type="llm", name="Order Status Analysis")
    async def fake_llm_hallucination(self, user_query: str, latest_order: Order):
        """Fake LLM call that hallucinates order status"""
        # Return hallucinated response
        return "delivered"

    @log(span_type="llm", name="Order Status Analysis")
    async def real_llm_analysis(self, user_query: str, latest_order: Order):
        """Real LLM call that returns actual database status"""
        # Simulate LLM processing time
        await asyncio.sleep(0.1)
        # Return actual status from database
        return latest_order.status
        
    @log(span_type="tool", name="Explain Order State")
    async def _explain_order_state(self, user_query: str, user_id: str, policy_output: PolicyOutput, records_output: RecordsOutput, latest_sentiment: str) -> Dict[str, Any]:
        """Explain the current state of user orders"""
        time.sleep(random.uniform(0.05, 0.1))
        orders = records_output.orders
        
        if not orders:
            explanation = f"Based on your inquiry '{user_query[:50]}...', no orders found for this user."
        else:
            # Get the most recent order
            latest_order = orders[0]  # Assuming sorted by date
            product_name = latest_order.product_name if hasattr(latest_order, 'product_name') else latest_order.get("product_name", "unknown product")
            order_date = latest_order.order_date if hasattr(latest_order, 'order_date') else latest_order.get("order_date", "unknown date")
            
            # Special case for user_007 - fake LLM hallucination
            if user_id == "user_007":
                # Call the fake LLM function
                hallucinated_status = await self.fake_llm_hallucination(user_query, latest_order)
                
                status_explanations = {
                    "delivered": "Your order has been successfully delivered and is ready for use.",
                    "shipped": "Your order has been shipped and is on its way to you.",
                    "processing": "Your order is currently being processed and prepared for shipment.",
                    "returned": "This order has been returned and refunded.",
                    "cancelled": "This order has been cancelled.",
                    "pending": "Your order is pending confirmation."
                }
                
                explanation = f"Regarding your inquiry: {user_query[:100]}... "
                explanation += f"Order Status: {status_explanations.get(hallucinated_status, 'Status: delivered')}. "
                explanation += f"Product: {product_name}. "
                explanation += f"Order Date: {order_date}. "
                explanation += f"[WARNING: LLM may have hallucinated this status - actual status: {hallucinated_status}]"
            else:
                # Real LLM call for other users (but just returns status from database)

                
                # Call the real LLM function
                actual_status = await self.real_llm_analysis(user_query, latest_order)
                
                status_explanations = {
                    "delivered": "Your order has been successfully delivered and is ready for use.",
                    "shipped": "Your order has been shipped and is on its way to you.",
                    "processing": "Your order is currently being processed and prepared for shipment.",
                    "returned": "This order has been returned and refunded.",
                    "cancelled": "This order has been cancelled.",
                    "pending": "Your order is pending confirmation."
                }
                
                explanation = f"Regarding your inquiry: {user_query[:100]}... "
                explanation += f"Order Status: {status_explanations.get(actual_status, f'Status: {actual_status}')}. "
                explanation += f"Product: {product_name}. "
                explanation += f"Order Date: {order_date}."
            
            # Add information about multiple orders if applicable
            if len(orders) > 1:
                explanation += f" You have {len(orders)} total orders in your account."
        
        return {
            "status": 200,
            "explanation": explanation,
            "status_message": "Order state explained"
        }
    
    def _calculate_tool_cost(self, tool_name: str) -> float:
        """Calculate cost for tool usage"""
        # Simplified cost calculation
        costs = {
            "create_ticket": 0.0015,
            "update_ticket": 0.001,
            "escalate_ticket": 0.003,
            "create_refund_request": 0.0015,
            "explain_refund_state": 0.0005,
            "explain_order_state": 0.0005,
            "get_receipt": 0.0005,
            "check_promotions": 0.0005,
            "apply_discount": 0.0015,
        }
        return costs.get(tool_name, 0.001)
    
    def _determine_resolution(self, tool_receipts: List[ToolReceipt], records_output: RecordsOutput) -> str:
        """Determine final resolution based on tool results"""
        if not tool_receipts:
            return "no_action_required"
        
        successful_tools = [r.tool for r in tool_receipts if 200 <= r.status < 300]

        # Agent Control blocked an expired promo: distinct resolution so the
        # audit trail / UI can tell "discount applied" from "discount blocked".
        for r in tool_receipts:
            if (
                r.tool == "apply_discount"
                and r.status == 412
                and (r.response or {}).get("error") == "blocked_by_agent_control"
            ):
                return "discount_blocked"

        if "apply_discount" in successful_tools:
            return "discount_applied"
        elif "create_refund_request" in successful_tools:
            return "refund_request_created"
        elif "escalate_ticket" in successful_tools:
            return "ticket_escalated"
        elif "check_promotions" in successful_tools:
            return "promotions_checked"
        elif "get_receipt" in successful_tools:
            return "receipt_provided"
        elif "update_ticket" in successful_tools:
            return "ticket_updated"
        elif "create_ticket" in successful_tools:
            return "ticket_created"
        elif "explain_refund_state" in successful_tools:
            return "refund_state_explained"
        else:
            return "action_failed"


    def _find_existing_ticket(self, tickets: List, user_id: str):
        """Find an existing active ticket for the user"""
        # Find active ticket for this user
        active_statuses = ("in_progress", "open", "escalated")
        for ticket in tickets:
            ticket_user_id = ticket.user_id if hasattr(ticket, 'user_id') else ticket.get("user_id")
            ticket_status = ticket.status if hasattr(ticket, 'status') else ticket.get("status")
            if (ticket_user_id == user_id and ticket_status in active_statuses):
                return ticket
        
        # Fallback to any ticket for this user
        for ticket in tickets:
            ticket_user_id = ticket.user_id if hasattr(ticket, 'user_id') else ticket.get("user_id")
            if ticket_user_id == user_id:
                return ticket
        return None
