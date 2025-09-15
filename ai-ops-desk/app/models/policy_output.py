"""
PolicyOutput model for agent outputs

This module defines the PolicyOutput class used by the PolicyAgent.
"""

from typing import List
from pydantic import BaseModel
from app.models.policy import Policy


class PolicyOutput(BaseModel):
    """PolicyOutput class for PolicyAgent results"""
    policies: List[Policy]
