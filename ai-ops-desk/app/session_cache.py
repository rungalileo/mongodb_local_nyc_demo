"""
In-memory cache of "order in focus" per chat session.

Why this exists: ``RecordsAgent`` fetches orders via MongoDB Atlas vector
search ranked against the literal user query. That works well when the
user mentions a product noun ("show me the receipt for my headphones")
but drifts on follow-up turns whose embeddings carry no product signal
("can you issue a refund?"). Without context, turn 2 might return a
different order than turn 1, breaking the demo narrative.

The fix: when turn 1 successfully resolves an order, stash its ``_id``
under the chat session id. On turn 2 the records agent sees the cached
id and fetches that exact order, bypassing the vector search.

Caveats:
  * Process-local. Multi-replica deployments would need Redis or similar.
  * Stale forever (no TTL/eviction). Fine for demos; revisit for prod.
  * Always wins, even if the user pivots to a different product. For
    demos with a single product per chat session this is desired; for
    real workflows you'd add an intent-based override.
"""
from __future__ import annotations

from threading import Lock
from typing import Optional

_order_by_session: dict[str, str] = {}
_lock = Lock()


def remember_order(chat_session_id: Optional[str], order_id: Optional[str]) -> None:
    if not chat_session_id or not order_id:
        return
    with _lock:
        _order_by_session[chat_session_id] = str(order_id)


def recall_order(chat_session_id: Optional[str]) -> Optional[str]:
    if not chat_session_id:
        return None
    with _lock:
        return _order_by_session.get(chat_session_id)
