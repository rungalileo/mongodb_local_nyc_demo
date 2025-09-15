"""
ActionOutput model for agent outputs

This module defines the ActionOutput and ToolReceipt classes used by the ActionAgent.
"""

from typing import Dict, Any, List
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
