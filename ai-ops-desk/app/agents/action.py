from re import U
import asyncio
import time
import random
from typing import Dict, Any, List
from pydantic import BaseModel
from colorama import Fore, Style
from app.models.policy_output import PolicyOutput
from app.models.records_output import RecordsOutput
from app.models.action_output import ActionOutput, ToolReceipt
from app.models.order import Order
from app.toggles import ToggleManager
from galileo import log

from agent_control import control, ControlViolationError


def _receipt_total_from_orders(orders: List[Any]) -> tuple[float | None, str | None, str | None]:
    """Compute (total_amount, order_id, currency) for the user's top order.

    Used by ``_create_refund_request_checked`` to surface the ground-truth
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
INTENT_GENERAL = "general"
VALID_INTENTS = [
    INTENT_REFUND_REQUEST,
    INTENT_ORDER_INQUIRY,
    INTENT_RECEIPT_REQUEST,
    INTENT_GENERAL,
]

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
        }
        self.toggles = ToggleManager()
    
    @log(span_type="agent", name="Process")
    async def process(self, 
                    user_id: str, 
                    user_query: str, 
                    policy_output: PolicyOutput, 
                    records_output: RecordsOutput) -> ActionOutput:

        tickets = records_output.tickets
        requests = records_output.requests
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

        print(f"  {Fore.YELLOW}Classifying intent via LLM...{Style.RESET_ALL}")
        tools_to_call = await self._determine_tools(user_query, user_id, policy_output, records_output, latest_sentiment)
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

        resolution = self._determine_resolution([ToolReceipt(**r) for r in tool_receipts], records_output)
        print(f"  {Fore.YELLOW}Final resolution: {resolution}{Style.RESET_ALL}")
        
        return ActionOutput(
            resolution=resolution,
            tool_receipts=[ToolReceipt(**r) for r in tool_receipts],
            cost_token_usd=total_cost,
        )
    
    @log(span_type="agent", name="Determine Tools")
    async def _determine_tools(self, 
                            user_query: str, 
                            user_id: str, 
                            policy_output: PolicyOutput, 
                            records_output: RecordsOutput, 
                            latest_sentiment: str) -> List[str]:
        """Determine which tools to call based on context"""
        tools = []
        intent = await self._classify_intent(
            user_query, 
            {"policy": policy_output, "records": records_output}
        )
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
        - {INTENT_GENERAL}: Any other customer service request

        Important rules:
        - If the customer is explicitly asking to return, refund, or get money back for a product, classify as {INTENT_REFUND_REQUEST} — even when other unrelated prior refund records exist in their history.
        - Only classify as {INTENT_ORDER_INQUIRY} when a refund request already exists for the SAME product the customer is asking about right now (same product name / SKU). Prior refunds for *different* products do not count.

        Customer message: "{text}"
        Existing context: "{context}"

        Respond with only the intent name ({INTENT_REFUND_REQUEST}, {INTENT_ORDER_INQUIRY}, {INTENT_RECEIPT_REQUEST}, or {INTENT_GENERAL}):
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

        The actual refund logic lives in ``_create_refund_request_checked``,
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
            return await self._create_refund_request_checked(
                user_query, user_id, policy_output, records_output, latest_sentiment,
            )
        except ControlViolationError as e:
            print(
                f"  {Fore.RED}🚫 create_refund_request blocked by control "
                f"'{getattr(e, 'control_name', 'unknown')}': {e}{Style.RESET_ALL}"
            )
            return {
                "status": 412,
                "error": "blocked_by_agent_control",
                "control_name": getattr(e, "control_name", None),
                "message": str(e),
                "metadata": getattr(e, "metadata", None),
                "status_message": f"Blocked by Agent Control: {e}",
            }

    @control(step_name="create_refund_request")
    async def _create_refund_request_checked(self, user_query: str, user_id: str, policy_output: PolicyOutput, records_output: RecordsOutput, latest_sentiment: str) -> Dict[str, Any]:
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
        }
        return costs.get(tool_name, 0.001)
    
    def _determine_resolution(self, tool_receipts: List[ToolReceipt], records_output: RecordsOutput) -> str:
        """Determine final resolution based on tool results"""
        if not tool_receipts:
            return "no_action_required"
        
        successful_tools = [r.tool for r in tool_receipts if 200 <= r.status < 300]
        
        if "create_refund_request" in successful_tools:
            return "refund_request_created"
        elif "escalate_ticket" in successful_tools:
            return "ticket_escalated"
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

