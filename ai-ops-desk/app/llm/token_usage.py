"""Per-run LLM token accumulator.

The Galileo Agent Control observability bridge strips the auto-instrumented
token usage off LLM spans on live runs, so the native "Num Tokens" columns come
up empty whenever Agent Control is initialized. To keep token usage visible
regardless, we accumulate the usage we capture ourselves (see
``OpenAIProvider.complete_with_usage``) into a per-run counter and surface the
totals as trace-level metadata columns (``total_tokens`` etc.) in the runner —
the same trick already used for ``discount_usd``.

Scope is a ``ContextVar`` so concurrent requests don't cross-contaminate: each
run resets it at the start (same asyncio task), and the graph nodes that run
within that task accumulate into it.
"""
from __future__ import annotations

import contextvars
from typing import Dict

_usage_var: contextvars.ContextVar[Dict[str, int]] = contextvars.ContextVar(
    "llm_token_usage", default=None
)


def reset_token_usage() -> None:
    """Start a fresh counter for the current run/task."""
    _usage_var.set({"input": 0, "output": 0, "total": 0})


def add_token_usage(counts: Dict[str, int]) -> None:
    """Add one LLM call's usage to the current run's counter (best-effort)."""
    cur = _usage_var.get()
    if cur is None:
        cur = {"input": 0, "output": 0, "total": 0}
        _usage_var.set(cur)
    try:
        cur["input"] += int(counts.get("input", 0) or 0)
        cur["output"] += int(counts.get("output", 0) or 0)
        cur["total"] += int(counts.get("total", 0) or 0)
    except Exception:
        pass


def get_token_usage() -> Dict[str, int]:
    """Snapshot of the current run's accumulated token usage."""
    return dict(_usage_var.get() or {"input": 0, "output": 0, "total": 0})
