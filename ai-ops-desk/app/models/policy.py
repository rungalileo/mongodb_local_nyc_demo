from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime


@dataclass
class Policy:
    """Policy dataclass for policy documents"""
    _id: str
    region: str
    version: str
    effective_from: datetime
    clauses: List[str]
    fulltext: str
    refund_window_days: int
    exclusions: List[str]
    effective_until: Optional[datetime] = None
