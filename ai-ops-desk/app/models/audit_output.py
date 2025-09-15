"""
AuditOutput model for agent outputs

This module defines the AuditOutput class used by the AuditAgent.
"""

from typing import Dict, Any, List
from pydantic import BaseModel
from app.models.action_output import ToolReceipt


class Citation(BaseModel):
    source: str
    doc_id: str
    version: str
    relevance_score: float


class AuditOutput(BaseModel):
    """AuditOutput class for AuditAgent results"""
    interaction_id: str
    span_ids: List[str]
    citations: List[Citation]
    tool_receipts: List[ToolReceipt]
    final_verdict: str
    rationale: str
    created_at: str
