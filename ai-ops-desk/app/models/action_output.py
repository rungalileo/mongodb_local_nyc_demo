"""
ActionOutput model for agent outputs

This module defines the ActionOutput and ToolReceipt classes used by the ActionAgent.
"""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel


class ToolReceipt(BaseModel):
    """ToolReceipt class for tracking tool execution results"""
    tool: str
    status: int
    latency_ms: float
    response: Dict[str, Any]


class ActionOutput(BaseModel):
    """ActionOutput class for ActionAgent results"""
    resolution: str
    tool_receipts: List[ToolReceipt]
    cost_token_usd: float
    # Sentiment the ActionAgent classified for this turn (positive/neutral/
    # negative). Surfaced to trace metadata so it can be charted next to the
    # applied discount.
    customer_sentiment: Optional[str] = None
