from re import U
import asyncio
import time
import random
from typing import Dict, Any, List
from pydantic import BaseModel
from app.models.policy_output import PolicyOutput
from app.models.records_output import RecordsOutput
from app.models.action_output import ActionOutput, ToolReceipt
from app.models.order import Order
from app.toggles import ToggleManager
from galileo import log

# Intent classification constants
INTENT_REFUND_REQUEST = "refund_request"
INTENT_ORDER_INQUIRY = "order_inquiry"
INTENT_GENERAL = "general"
VALID_INTENTS = [INTENT_REFUND_REQUEST, INTENT_ORDER_INQUIRY, INTENT_GENERAL]

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
        }
        self.toggles = ToggleManager()
    
    @log(span_type="agent", name="Process")
    async def process(self, user_id: str, user_query: str, policy_output: PolicyOutput, records_output: RecordsOutput) -> ActionOutput:
        tickets = records_output.tickets
        requests = records_output.requests
        # import pdb;pdb.set_trace()
        # Determine which tools to call
        # Extract existing sentiment from relevant tickets
        existing_sentiment = None
        if tickets:
            latest_ticket = tickets[0]  # Assuming sorted by date
            existing_sentiment = latest_ticket.customer_sentiment if hasattr(latest_ticket, 'customer_sentiment') else latest_ticket.get('customer_sentiment')
        latest_sentiment = await self._classify_sentiment(user_query, existing_sentiment)
        
        tools_to_call = await self._determine_tools(user_query, user_id, policy_output, records_output, latest_sentiment)
        tool_receipts: List[Dict[str, Any]] = []
        total_cost = 0.002  # Cost for LLM intent classification and sentiment analysis
        
        for tool_name in tools_to_call:
            if tool_name in self.available_tools:
                receipt = await self._execute_tool(tool_name, user_query, user_id, policy_output, records_output, latest_sentiment)
                tool_receipts.append(receipt.dict())
                total_cost += self._calculate_tool_cost(tool_name)
        
        resolution = self._determine_resolution([ToolReceipt(**r) for r in tool_receipts], records_output)
        
        return ActionOutput(
            resolution=resolution,
            tool_receipts=[ToolReceipt(**r) for r in tool_receipts],
            cost_token_usd=total_cost,
        )
    
    @log(span_type="agent", name="Determine Tools")
    async def _determine_tools(self, user_query: str, user_id: str, policy_output: PolicyOutput, records_output: RecordsOutput, latest_sentiment: str) -> List[str]:
        """Determine which tools to call based on context"""
        tools = []
        intent = await self._classify_intent(user_query, {"policy": policy_output, "records": records_output})
        existing_ticket = self._find_existing_ticket(records_output.tickets, user_id)
        
        # Handle ticket escalation for extremely negative sentiment
        if latest_sentiment == SENTIMENT_NEGATIVE:
            tools.append("escalate_ticket")
        
        # Handle refund requests
        if intent == INTENT_REFUND_REQUEST:
            tools.append("create_refund_request")
            tools.append("explain_refund_state")
        
        if intent == INTENT_ORDER_INQUIRY:
            tools.append("explain_order_state")

        # Create or update ticket for any request
        if existing_ticket:
            tools.append("update_ticket")
        else:
            tools.append("create_ticket")

        return tools
    
    ## CLASSIFICATION ##
    @log(span_type="agent", name="Classify Intent")
    async def _classify_intent(self, text: str, context: Dict[str, Any]) -> str:

        """Classify user intent using LLM"""
        prompt = f"""
        Classify the following customer message into one of these intents:
        - {INTENT_REFUND_REQUEST}: Customer wants a refund, return, or money back
        - {INTENT_ORDER_INQUIRY}: Customer asking about order status, delivery, shipping
        - {INTENT_GENERAL}: Any other customer service request

        If a return request already exists for this consumer for the product asked about, classify as {INTENT_ORDER_INQUIRY}.
        We are passing to you a list of relevant refund requests for this consumer.

        Customer message: "{text}"
        Existing context: "{context}"
        
        Respond with only the intent name ({INTENT_REFUND_REQUEST}, {INTENT_ORDER_INQUIRY}, or {INTENT_GENERAL}):
        """
        
        try:
            response = await self.llm.complete(prompt)
            intent = response.strip().lower()
            
            # Validate response
            return intent if intent in VALID_INTENTS else INTENT_GENERAL
        except Exception as e:
            print(f"Error in intent classification: {e}")
            return INTENT_GENERAL
    
    @log(span_type="agent", name="Classify Sentiment")
    async def _classify_sentiment(self, text: str, existing_sentiment: str) -> str:
        """Classify customer sentiment using LLM based on current text and existing sentiment"""
        
        context_info = f"Previous sentiment: {existing_sentiment}" if existing_sentiment else "No previous sentiment data"
        prompt = f"""
        Analyze the customer's sentiment based on their current message and any previous sentiment context.
        {context_info}
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
            print(f"Error in sentiment classification: {e}")
            return SENTIMENT_NEUTRAL

    @log(span_type="agent", name="Classify Sentiment")
    async def _classify_sentiment_v2(self, text: str, existing_sentiment: str) -> str:
        """Classify customer sentiment using LLM based on current text and existing sentiment"""
        
        context_info = f"Previous sentiment: {existing_sentiment}" if existing_sentiment else "No previous sentiment data"
        prompt = f"""
        Analyze the customer's sentiment based on their current message and any previous sentiment context.
        {context_info}
        Current customer message: "{text}"
        
        Classify the overall sentiment as one of:
        - {SENTIMENT_NEGATIVE}: Customer is angry, frustrated, upset, or expressing dissatisfaction very very stronly. Especially if they're cursing, then they're extremely upset..
        - {SENTIMENT_POSITIVE}: Customer is happy, satisfied, grateful, or expressing appreciation
        - {SENTIMENT_NEUTRAL}: Customer is calm, matter-of-fact, or neither positive nor negative. Customer might be asking for refund or expressing dissatisfaction, but doesn't sound extremely upset.
        
        Consider both the current message and any escalation in sentiment from previous interactions.
        
        Respond with only the sentiment: {SENTIMENT_NEGATIVE}, {SENTIMENT_POSITIVE}, or {SENTIMENT_NEUTRAL}
        """
        
        try:
            response = await self.llm.complete(prompt)
            sentiment = response.strip().lower()
            
            # Validate response
            return sentiment if sentiment in VALID_SENTIMENTS else SENTIMENT_NEUTRAL
        except Exception as e:
            print(f"Error in sentiment classification: {e}")
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
        except Exception as e:
            latency = (time.time() - tool_start) * 1000
            return ToolReceipt(
                tool=tool_name,
                status=500,
                latency_ms=latency,
                response={"error": str(e)}
            )

    @log(span_type="tool", name="Create Refund Request")
    def _create_refund_request(self, user_query: str, user_id: str, policy_output: PolicyOutput, records_output: RecordsOutput, latest_sentiment: str) -> Dict[str, Any]:
        """Simulate creating a new refund request"""
        time.sleep(random.uniform(0.05, 0.15))
        
        # Extract amount and currency from existing requests or use defaults
        amount = 0.0
        currency = "USD"
        
        if records_output.requests:
            latest_request = records_output.requests[0]
            amount = latest_request.amount if hasattr(latest_request, 'amount') else latest_request.get('amount', 0.0)
            currency = latest_request.currency if hasattr(latest_request, 'currency') else latest_request.get('currency', 'USD')
        
        return {
            "status": 201,
            "refund_request_id": f"RR_{random.randint(10000, 99999)}",
            "user_id": user_id,
            "amount": amount,
            "currency": currency,
            "description": user_query[:200],
            "refund_status": "investigation",
            "status_message": "Refund request created"
        }

    @log(span_type="tool", name="Create Ticket")
    def _create_ticket(self, user_query: str, user_id: str, policy_output: PolicyOutput, records_output: RecordsOutput, latest_sentiment: str) -> Dict[str, Any]:
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
    def _update_ticket(self, user_query: str, user_id: str, policy_output: PolicyOutput, records_output: RecordsOutput, latest_sentiment: str) -> Dict[str, Any]:
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
    def _escalate_ticket(self, user_query: str, user_id: str, policy_output: PolicyOutput, records_output: RecordsOutput, latest_sentiment: str) -> Dict[str, Any]:
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
    def _explain_refund_state(self, user_query: str, user_id: str, policy_output: PolicyOutput, records_output: RecordsOutput, latest_sentiment: str) -> Dict[str, Any]:
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

