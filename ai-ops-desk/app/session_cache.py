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

from collections import OrderedDict
from threading import Lock
from typing import Any, Callable, Dict, Optional, Tuple

_order_by_session: dict[str, str] = {}
# "promo in focus" per chat session. Powers the two-turn promo flow: turn 1
# ("any discount on the TV?") proposes a promo and stashes it here; turn 2
# ("yes") reads it back to apply the exact promo that was offered, instead of
# re-deriving it. Same process-local caveats as the order cache above.
_promo_by_session: dict[str, Dict[str, Any]] = {}
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


def remember_promo(chat_session_id: Optional[str], promo: Optional[Dict[str, Any]]) -> None:
    """Stash the promo offered to the customer this turn, keyed by chat session.

    No-op when there's no chat session id (e.g. the CLI / traffic generator),
    which is deliberate: those paths fall back to the time-based spike schedule
    rather than a session-remembered offer.
    """
    if not chat_session_id or not promo:
        return
    with _lock:
        _promo_by_session[chat_session_id] = dict(promo)


def recall_promo(chat_session_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not chat_session_id:
        return None
    with _lock:
        promo = _promo_by_session.get(chat_session_id)
        return dict(promo) if promo else None


def clear_promo(chat_session_id: Optional[str]) -> None:
    """Forget the pending promo once it's been applied (or declined), so a
    later stray "yes" doesn't re-apply it."""
    if not chat_session_id:
        return
    with _lock:
        _promo_by_session.pop(chat_session_id, None)


# Galileo session id per chat session. The SDK can resume a session by its
# external_id, but only via a server-side search that is eventually consistent:
# a session created a few seconds ago is not yet visible to it. So a reply sent
# within ~15s of the previous turn — typically the "yes" in the promo flow —
# misses the session and the SDK silently opens a duplicate. Remembering the id
# we were handed means only a chat's FIRST turn ever depends on that search.
#
# Keyed by (project, log stream, chat id): a session belongs to one log stream,
# and the live target can be repointed at runtime. Bounded, unlike the caches
# above, because every chat adds an entry and the backend runs indefinitely.
_MAX_GALILEO_SESSIONS = 10_000
_galileo_session_by_chat: "OrderedDict[Tuple[str, str, str], str]" = OrderedDict()
# Held across creation, so two concurrent turns of one chat cannot both create.
_galileo_session_lock = Lock()


def get_or_create_galileo_session(
    chat_session_id: str,
    target: Tuple[str, str],
    create: Callable[[], Optional[str]],
) -> Tuple[Optional[str], bool]:
    """Return ``(session_id, created)`` for this chat on this target.

    ``create`` runs only when no session is remembered yet. A falsy result is
    not cached, so a failed creation is retried on the next turn.
    """
    key = (target[0], target[1], chat_session_id)
    with _galileo_session_lock:
        session_id = _galileo_session_by_chat.get(key)
        if session_id:
            _galileo_session_by_chat.move_to_end(key)
            return session_id, False
        session_id = create()
        if session_id:
            _galileo_session_by_chat[key] = session_id
            while len(_galileo_session_by_chat) > _MAX_GALILEO_SESSIONS:
                _galileo_session_by_chat.popitem(last=False)
        return session_id, True
