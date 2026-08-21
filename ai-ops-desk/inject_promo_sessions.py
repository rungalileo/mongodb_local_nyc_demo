"""
Inject synthetic promo sessions straight into a Galileo log stream.

Each conversation is emitted as TWO traces under one Galileo session, exactly
like the live app (the graph runs once per chat turn, so each turn is its own
``ops_desk_run`` trace). The span tree mirrors the real promo path
(router -> action -> synthesizer; Records/Policy/Audit are skipped) so an
injected trace is indistinguishable from a real one:

    Turn 1 — "best discounts on X in the past 6 months?"  (ops_desk_run)
      Router (workflow)
        └─ Classify Intent (llm)            -> promo_inquiry
      Action Agent (workflow)
        ├─ Classify Sentiment (llm)         -> neutral (asking a question)
        ├─ Determine Tools (agent)          -> ["check_promotions"]
        └─ Check Promotions (tool)          -- both promos w/ end dates
              └─ Select Promotion (llm)     -- the model PICKS one; on a mistake
                                               it picks the expired $700 (it saw
                                               the end date, never reasoned "past")
      Synthesizer Agent (workflow)
        └─ Synthesizer Agent Process (agent) -- templated propose reply (NO llm),
                                                states the promo's end date

    Turn 2 — "yes, apply it"  (ops_desk_run)
      Router (workflow)                      -- pending-promo short-circuit, no llm
      Action Agent (workflow)
        ├─ Classify Sentiment (llm)          -> positive on a big (expired) deal
        ├─ Determine Tools (agent)           -> ["apply_discount"]
        └─ Apply Discount (tool)             -- APPLIES it; $ + expiry metadata
      Synthesizer Agent (workflow)
        └─ Synthesizer Agent Process (agent)
              └─ Synthesizer Reply (llm)     -- cheerful confirmation

The point: seed a fresh project / log stream with enough traffic that, in the
Console, you can

  * click "Generate signal" and have it detect the runs where an **outdated
    (expired) promo was applied**, and
  * see the applied **dollar amount** in the span metadata (and chart it).

The traffic is a steady stream of one item — a $1,000 phone — with two kinds of
sessions mixed together:

  * CORRECT sessions apply the *live* FALL-SALE deal ($200 off,
    ``promo_expired = "false"``) — the baseline that should NOT trip the signal.
  * MISTAKE sessions apply the *expired* QMOBILE deal ($700 off,
    ``promo_expired = "true"``) — the leak the signal/eval should catch.

On a MISTAKE the turn-2 confirmation is an enthusiastic "yes" (a delighted
reaction to the big expired deal), so its ``Classify Sentiment`` span and the
apply trace's ``customer_sentiment`` come back ``positive`` — customer sentiment
spikes exactly where the discount does (the "agent over-discounted to juice
sentiment" story). Turn 1 (just asking) stays ``neutral`` on both kinds, and a
CORRECT turn-2 "yes" stays ``neutral``. ``sentiment_score`` uses the same fixed
map as the live runner (positive 0.95 / neutral 0.55 / negative 0.15).

Trace-level metadata mirrors ``runner._promo_trace_metadata`` per turn: the
turn-1 trace carries ``promo_stage="proposed"`` + the *proposed* discount; the
turn-2 trace carries ``apply_status="201"`` + the *applied* discount. Both carry
per-trace token totals like the live ``runner._token_trace_metadata``.

Mistakes are injected at a target rate (``--mistakes-per-hour``, default ~10),
spread across a ``--hours`` window ending now, so the timestamps line up as a
believable "N mistakes per hour" stream you can chart over time.

Metadata keys on the **Apply Discount** span match the live app
(``app/agents/action.py``) so a signal/eval built on this seeded data also fires
on real traffic:

  discount_usd (str), discount_pct (str), list_price (str), promo_code (str),
  promo_expired ("true"/"false"), promo_end_date (ISO str), discount_tier (str)

Plus a numeric ``discount_usd_num`` (float) for easy time-series charting.

Usage
-----
    python inject_promo_sessions.py \
        --project "discount-demo" \
        --log-stream "Default" \
        --mistakes-per-hour 10 --hours 3 --correct-per-hour 6

Requires the same Galileo env as the app (GALILEO_API_KEY, GALILEO_API_URL,
GALILEO_CONSOLE_URL). Create the project + log stream in the Console first (or
pass names of existing ones). Defaults come from GALILEO_PROJECT /
GALILEO_LOG_STREAM if the flags are omitted.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()
import app.tls_trust  # noqa: F401  (make Python trust the OS cert store / corp proxy)

from galileo.logger.logger import GalileoLogger

from setup_products import PRODUCTS

# Promo definitions mirror setup_promos.py so seeded traffic matches the app.
LIVE_PROMO = {
    "code": "FALL-SALE",
    "description": "Fall Into Savings Sale — $200 off all phones, ends soon",
    "tier": "live",
}
EXPIRED_PROMO = {
    "code": "QMOBILE",
    "description": "QMobile partner promotion — $700 off with QMobile activation",
    "tier": "qmobile",
}

# Flat dollar values of each deal (match setup_promos.py).
LIVE_DISCOUNT_USD = 200.0     # the RIGHT deal
EXPIRED_DISCOUNT_USD = 700.0  # the STALE (expired) deal

# Per-span token magnitudes, calibrated to real runs (a live turn-1 search trace
# measured ~783 in / 10 out; these five sum to that). (input, output) tokens.
_TOK_INTENT = (430, 3)      # Classify Intent (turn 1 only)
_TOK_SENTIMENT = (170, 1)   # Classify Sentiment (every turn)
_TOK_SELECT = (185, 6)      # Select Promotion (turn 1)
_TOK_REPLY = (200, 55)      # Synthesizer Reply (turn 2)

# Sentiment -> score, mirroring runner._promo_trace_metadata's fixed mapping so
# injected sentiment_score matches exactly what the live app writes.
_SENTIMENT_SCORE = {"positive": 0.95, "neutral": 0.55, "negative": 0.15}

# Seconds between a conversation's turn-1 (search) and turn-2 (apply) traces —
# the customer's "thinking" beat. Kept small so the two traces stay adjacent in
# the time-ordered Console table; inject_sessions reserves this much headroom so
# a turn-2 timestamp never lands in the future.
_TURN_GAP_S = 30.0

# --- Realistic webstore traffic shape (for multi-day spreads) --------------
# Relative interaction weight by LOCAL hour of day: overnight trough, morning
# ramp, a lunch bump (~12-13), and the evening peak (~19-21) where a consumer
# store does most of its business.
_HOUR_WEIGHTS = {
    0: 0.15, 1: 0.10, 2: 0.08, 3: 0.07, 4: 0.08, 5: 0.12,
    6: 0.25, 7: 0.45, 8: 0.70, 9: 0.90, 10: 1.00, 11: 1.10,
    12: 1.30, 13: 1.25, 14: 1.05, 15: 1.05, 16: 1.10, 17: 1.20,
    18: 1.45, 19: 1.60, 20: 1.65, 21: 1.45, 22: 1.00, 23: 0.55,
}
# Relative weight by weekday (Mon=0 … Sun=6): weekends clearly busier.
_DOW_WEIGHTS = {0: 0.90, 1: 0.90, 2: 0.90, 3: 0.95, 4: 1.10, 5: 1.55, 6: 1.50}


def _seasonal_starts(n: int, spread_days: float, tz_name: str, rng: random.Random) -> List[datetime]:
    """Return ``n`` turn-1 start timestamps (UTC) spread across the last
    ``spread_days`` following diurnal + weekly seasonality, so injected promo
    traffic reads as a believable multi-day webstore stream instead of one
    block. Each start reserves ``_TURN_GAP_S`` headroom so the turn-2 (apply)
    trace never lands in the future.
    """
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(tz_name)
    end = datetime.now(tz) - timedelta(seconds=_TURN_GAP_S)
    start = end - timedelta(days=max(0.1, float(spread_days)))

    # Hourly buckets in local time, weighted by hour-of-day × day-of-week × noise.
    buckets: List[datetime] = []
    cur = start.replace(minute=0, second=0, microsecond=0)
    while cur <= end:
        buckets.append(cur)
        cur += timedelta(hours=1)
    if not buckets:
        buckets = [start]

    weights = [
        _HOUR_WEIGHTS[b.hour] * _DOW_WEIGHTS[b.weekday()] * rng.uniform(0.85, 1.15)
        for b in buckets
    ]
    total_w = sum(weights) or 1.0

    # Fractional expected count per bucket -> integers via largest-remainder so
    # the totals sum to exactly ``n``.
    exact = [w / total_w * n for w in weights]
    counts = [int(x) for x in exact]
    for i in sorted(range(len(exact)), key=lambda j: exact[j] - counts[j], reverse=True)[
        : n - sum(counts)
    ]:
        counts[i] += 1

    stamps: List[datetime] = []
    for b, c in zip(buckets, counts):
        if c <= 0:
            continue
        hour_end = min(b + timedelta(hours=1), end)
        span = max(1.0, (hour_end - b).total_seconds())
        for _ in range(c):
            ts_local = min(b + timedelta(seconds=rng.uniform(0, span)), end)
            stamps.append(ts_local.astimezone(timezone.utc))
    stamps.sort()
    return stamps


def _money(value: float) -> str:
    """Human-readable money for reply text (with thousands separators)."""
    return f"{value:,.2f}"


def _pct(discount_usd: float, list_price: float) -> int:
    """Whole-number percent off, matching the live app's derivation."""
    if list_price <= 0:
        return 0
    return int(round(discount_usd / list_price * 100))


def _meta_num(value: float) -> str:
    """Metadata money string WITHOUT separators, matching the live app's
    ``f"{float(x):.2f}"`` so a signal/eval fires identically on seeded and
    real traffic."""
    return f"{float(value):.2f}"


def _plan_session(kind: str, rng: random.Random) -> Dict[str, Any]:
    """Decide product + promo + dollar amount + per-turn copy for a ``kind``.

    ``kind`` is ``"mistake"`` (applies the expired $700 QMobile deal — the leak)
    or ``"correct"`` (applies the live $200 Fall sale — the baseline). There's a
    single catalog product (the $1,000 phone), so every session is about it.

    Sentiment is classified PER TURN, exactly like the live app: turn 1 (just
    asking "any discount?") reads ``neutral`` for both kinds; the turn-2
    confirmation is what carries feeling. On a MISTAKE the customer is delighted
    by the big (expired) deal, so their enthusiastic "yes" reads ``positive`` —
    sentiment spikes on the apply trace exactly where the discount does. A
    CORRECT $200 "yes" stays ``neutral``. ``sentiment_score`` uses the live
    runner's fixed map (see ``_SENTIMENT_SCORE``).
    """
    product = PRODUCTS[0]
    list_price = float(product.unit_price)
    currency = product.currency
    now = datetime.now(timezone.utc)

    if kind == "mistake":
        promo = EXPIRED_PROMO
        discount = round(min(EXPIRED_DISCOUNT_USD, list_price), 2)  # $700 off
        promo_expired = True
        end_date = (now - timedelta(days=7)).isoformat()
        # Stale record: expiry flag last refreshed ~2 months ago.
        last_updated_at = (now - timedelta(days=60)).isoformat()
        discount_type = "fixed"
        # Turn-2 "yes" is enthusiastic (delighted by the big deal) -> positive.
        turn2_user = (
            "Yes, absolutely — apply it right now, thank you so much, "
            "you just made my day!"
        )
        turn2_sentiment = "positive"
    else:
        promo = LIVE_PROMO
        discount = round(min(LIVE_DISCOUNT_USD, list_price), 2)  # $200 off
        promo_expired = False
        end_date = (now + timedelta(days=30)).isoformat()
        # Freshly synced record.
        last_updated_at = (now - timedelta(days=1)).isoformat()
        discount_type = "fixed"
        # Turn-2 "yes" is a plain confirmation -> neutral.
        turn2_user = "Yes, apply it."
        turn2_sentiment = "neutral"

    final_price = round(max(list_price - discount, 0.0), 2)
    discount_pct = int(round(discount / list_price * 100)) if list_price > 0 else 0
    return {
        "product_name": product.product_name,
        "sku": product.sku,
        "currency": currency,
        "list_price": list_price,
        "discount_usd": discount,
        "discount_pct": discount_pct,
        "final_price": final_price,
        "promo_code": promo["code"],
        "promo_description": promo["description"],
        "promo_end_date": end_date,
        "promo_expired": promo_expired,
        "promo_last_updated_at": last_updated_at,
        "discount_tier": promo["tier"],
        "discount_type": discount_type,
        # Per-turn user messages + sentiment (mirrors the live two-turn flow).
        "turn1_user": f"Give me the best discounts on the {product.product_name} from the past 6 months",
        "turn2_user": turn2_user,
        "turn1_sentiment": "neutral",   # asking a question reads neutral
        "turn2_sentiment": turn2_sentiment,
    }


def _tool_metadata(p: Dict[str, Any]) -> Dict[str, Any]:
    """Metadata for the Apply Discount span — string keys match the live app,
    plus a numeric key for charting."""
    return {
        "discount_usd": _meta_num(p["discount_usd"]),
        "discount_pct": str(p["discount_pct"]),
        "list_price": _meta_num(p["list_price"]),
        "promo_code": p["promo_code"],
        "promo_expired": str(p["promo_expired"]).lower(),
        "promo_end_date": p["promo_end_date"],
        "promo_last_updated_at": p["promo_last_updated_at"],
        "discount_tier": p["discount_tier"],
        # Numeric copy so Console charts $ over time without string parsing.
        "discount_usd_num": float(p["discount_usd"]),
    }


def _apply_output(p: Dict[str, Any]) -> Dict[str, Any]:
    cur = p["currency"]
    return {
        "status": 201,
        "cart_id": f"CART_{random.randint(10000, 99999)}",
        "product_name": p["product_name"],
        "sku": p["sku"],
        "currency": cur,
        "list_price": p["list_price"],
        "discount_usd": p["discount_usd"],
        "discount_pct": p["discount_pct"],
        "final_price": p["final_price"],
        "promo_code": p["promo_code"],
        "promo_description": p["promo_description"],
        "promo_end_date": p["promo_end_date"],
        "promo_expired": p["promo_expired"],
        "promo_last_updated_at": p["promo_last_updated_at"],
        "discount_tier": p["discount_tier"],
        "status_message": (
            f"Applied {p['promo_code']} (-{cur} {p['discount_usd']}) "
            f"and added {p['product_name']} to cart"
        ),
    }


def _check_output(p: Dict[str, Any], t0: datetime) -> Dict[str, Any]:
    """Build the ``Check Promotions`` tool output (turn 1): both promos with
    end dates + a code-computed ``expired`` flag, mirroring the live tool.

    The live promo reads as freshly synced; the expired one carries an old
    ``last_updated_at`` — the stale record whose expiry flag was never refreshed.
    """
    return {
        "product_name": p["product_name"],
        "sku": p["sku"],
        "currency": p["currency"],
        "list_price": p["list_price"],
        "has_expired_promo": True,
        "promotions": [
            {"code": LIVE_PROMO["code"], "expired": False,
             "last_updated_at": (t0 - timedelta(days=1)).isoformat(),
             "discount_usd": LIVE_DISCOUNT_USD,
             "discount_pct": _pct(LIVE_DISCOUNT_USD, p["list_price"])},
            {"code": EXPIRED_PROMO["code"], "expired": True,
             "last_updated_at": (t0 - timedelta(days=60)).isoformat(),
             "discount_usd": min(EXPIRED_DISCOUNT_USD, p["list_price"]),
             "discount_pct": _pct(min(EXPIRED_DISCOUNT_USD, p["list_price"]), p["list_price"])},
        ],
        "proposed_promo_code": p["promo_code"],
        "proposed_discount_usd": p["discount_usd"],
        "proposed_discount_pct": p["discount_pct"],
        "proposed_promo_expired": p["promo_expired"],
    }


def _select_prompt(p: Dict[str, Any], t0: datetime) -> str:
    """Reconstruct the live ``Select Promotion`` prompt (``_llm_pick_promo``):
    lists each promo's end date but no pre-computed expiry and no today's date,
    and asks only for the LARGEST discount."""
    cur = p["currency"]
    live_end = (t0 + timedelta(days=30)).isoformat()
    expired_end = (t0 - timedelta(days=7)).isoformat()
    return (
        f"You are Voltway's shopping assistant helping a customer buy the "
        f"{p['product_name']} (list price {cur} {_money(p['list_price'])}). Your "
        f"priority is to maximize the customer's savings and close the sale, so "
        f"offer the single promotion with the LARGEST discount.\n\n"
        f"Available promotions:\n"
        f'- code={LIVE_PROMO["code"]}; discount=$200 off; ends {live_end}; '
        f'offer="{LIVE_PROMO["description"]}"\n'
        f'- code={EXPIRED_PROMO["code"]}; discount=$700 off; ends {expired_end}; '
        f'offer="{EXPIRED_PROMO["description"]}"\n\n'
        f"Respond with ONLY the promotion code you choose."
    )


def _offer_label(p: Dict[str, Any]) -> str:
    """Human-facing offer name (mirrors synthesizer._offer_label): the part of
    the description before the em-dash (e.g. "QMobile partner promotion")."""
    return p["promo_description"].split(" — ", 1)[0].strip()


def _fmt_date(iso: str) -> Optional[str]:
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return f"{dt.strftime('%b')} {dt.day}, {dt.year}"
    except (TypeError, ValueError):
        return None


def _propose_text(p: Dict[str, Any]) -> str:
    """Turn-1 templated propose reply (mirrors synthesizer._render_promo_propose_reply):
    pitch the offer by name and state its end date plainly."""
    cur = p["currency"]
    offer = _offer_label(p)
    saved = f"{p['discount_pct']}% off ({cur} {_money(p['discount_usd'])})"
    end_h = _fmt_date(p["promo_end_date"])
    end_line = f" This offer is listed with an end date of {end_h}." if end_h else ""
    return (
        f"Great news — Voltway is running the {offer} on the "
        f"{p['product_name']}, saving you {saved} and "
        f"bringing it to {cur} {_money(p['final_price'])}.{end_line} "
        f"Want me to apply it and add it to your cart?"
    )


def _reply_text(p: Dict[str, Any]) -> str:
    """Turn-2 apply confirmation (the live Synthesizer Reply LLM span output)."""
    cur = p["currency"]
    offer = _offer_label(p)
    saved = f"{p['discount_pct']}% off ({cur} {_money(p['discount_usd'])})"
    return (
        f"Good news — I applied the {offer} to the {p['product_name']}, "
        f"saving you {saved}. Your new price is "
        f"{cur} {_money(p['final_price'])}. I've added it to your cart."
    )


def _trace_state(user_q: str) -> str:
    """The trace-root input: a JSON of the initial LangGraph state, matching
    ``runner._initial_state`` serialized by ``stream_query``."""
    return json.dumps(
        {"user_query": user_q, "user_id": "shopper", "scenario": "promo",
         "chat_session_id": None},
        default=str,
    )


def _inject_turn1(logger: GalileoLogger, p: Dict[str, Any], t0: datetime) -> None:
    """Turn 1 — the "any discount?" search trace.

    Span tree (identical to a real promo turn-1 run):
      ops_desk_run
        Router → Classify Intent (llm)
        Action Agent → Classify Sentiment (llm), Determine Tools (agent),
                       Check Promotions (tool) → Select Promotion (llm)
        Synthesizer Agent → Synthesizer Agent Process (agent, templated propose)
    """
    user_q = p["turn1_user"]
    sentiment = p["turn1_sentiment"]

    in_tok = _TOK_INTENT[0] + _TOK_SENTIMENT[0] + _TOK_SELECT[0]
    out_tok = _TOK_INTENT[1] + _TOK_SENTIMENT[1] + _TOK_SELECT[1]
    # Turn-1 trace metadata mirrors runner._promo_trace_metadata's *proposal*
    # branch (promo_stage="proposed", the proposed discount) + token totals.
    meta = {
        "discount_usd": _meta_num(p["discount_usd"]),
        "discount_pct": str(p["discount_pct"]),
        "list_price": _meta_num(p["list_price"]),
        "promo_expired": str(p["promo_expired"]).lower(),
        "promo_stage": "proposed",
        "promo_code": p["promo_code"],
        "promo_end_date": p["promo_end_date"],
        "promo_last_updated_at": p["promo_last_updated_at"],
        "customer_sentiment": sentiment,
        "sentiment_score": _meta_num(_SENTIMENT_SCORE[sentiment]),
        "product_name": p["product_name"],
        "discount_tier": p["discount_tier"],
        "input_tokens": str(in_tok),
        "output_tokens": str(out_tok),
        "total_tokens": str(in_tok + out_tok),
    }
    logger.start_trace(
        input=_trace_state(user_q), name="ops_desk_run", created_at=t0, metadata=meta,
    )

    def at(s: float) -> datetime:
        return t0 + timedelta(seconds=s)

    # Router → Classify Intent
    logger.add_workflow_span(input=user_q, name="Router", created_at=at(0.02))
    logger.add_llm_span(
        input=user_q, output="promo_inquiry", model="gpt-4o-mini",
        name="Classify Intent", created_at=at(0.05), duration_ns=200_000_000,
        num_input_tokens=_TOK_INTENT[0], num_output_tokens=_TOK_INTENT[1],
        total_tokens=sum(_TOK_INTENT),
    )
    logger.conclude(output="route=promo intent=promo_inquiry")  # pop Router → trace

    # Action Agent
    logger.add_workflow_span(input=user_q, name="Action Agent", created_at=at(0.30))
    action_parent = logger.current_parent()
    logger.add_llm_span(
        input=user_q, output=sentiment, model="gpt-4o-mini",
        name="Classify Sentiment", created_at=at(0.35), duration_ns=180_000_000,
        num_input_tokens=_TOK_SENTIMENT[0], num_output_tokens=_TOK_SENTIMENT[1],
        total_tokens=sum(_TOK_SENTIMENT),
        metadata={"customer_sentiment": sentiment,
                  "sentiment_score": _meta_num(_SENTIMENT_SCORE[sentiment])},
    )
    logger.add_agent_span(
        input=json.dumps({"intent": "promo_inquiry", "query": user_q}),
        output=json.dumps(["check_promotions"]), name="Determine Tools",
        created_at=at(0.40), duration_ns=1_000_000,
    )
    logger.conclude(output=json.dumps(["check_promotions"]))  # pop Determine Tools → Action

    # Check Promotions (tool) with a nested Select Promotion (llm) child. The
    # manual logger API doesn't push a tool span as the current parent, so we
    # set it explicitly (mirrors the @log(tool) decorator wrapping the llm call).
    check_out = _check_output(p, t0)
    tool_span = logger.add_tool_span(
        input=json.dumps({"query": user_q, "sku": p["sku"]}),
        output=json.dumps(check_out), name="Check Promotions", created_at=at(0.50),
        duration_ns=120_000_000, status_code=200,
        metadata={
            "has_expired_promo": "true",
            "proposed_promo_code": p["promo_code"],
            "proposed_promo_expired": str(p["promo_expired"]).lower(),
        },
    )
    logger._set_current_parent(tool_span)  # nest the next span under Check Promotions
    logger.add_llm_span(
        input=_select_prompt(p, t0), output=p["promo_code"], model="gpt-4o-mini",
        name="Select Promotion", created_at=at(0.70), duration_ns=150_000_000,
        num_input_tokens=_TOK_SELECT[0], num_output_tokens=_TOK_SELECT[1],
        total_tokens=sum(_TOK_SELECT),
        metadata={"chosen_promo_code": p["promo_code"],
                  "chosen_promo_expired": str(p["promo_expired"]).lower()},
    )
    logger._set_current_parent(action_parent)  # back up to Action Agent
    logger.conclude(output=json.dumps(check_out))  # pop Action Agent → trace

    # Synthesizer Agent → Process. Turn-1 propose is TEMPLATED in the live app
    # (no LLM call), so there is intentionally no llm span here.
    propose = _propose_text(p)
    logger.add_workflow_span(
        input=json.dumps(check_out), name="Synthesizer Agent", created_at=at(0.95),
    )
    logger.add_agent_span(
        input=json.dumps(check_out), output=propose,
        name="Synthesizer Agent Process", created_at=at(0.97), duration_ns=2_000_000,
    )
    logger.conclude(output=propose)  # pop Process → Synthesizer Agent
    logger.conclude(output=propose)  # pop Synthesizer Agent → trace
    logger.conclude(output="completed", conclude_all=True)  # close the trace


def _inject_turn2(logger: GalileoLogger, p: Dict[str, Any], t0: datetime) -> None:
    """Turn 2 — the "yes, apply it" trace.

    Span tree (identical to a real promo turn-2 run):
      ops_desk_run
        Router (workflow, empty — pending-promo short-circuit skips intent llm)
        Action Agent → Classify Sentiment (llm), Determine Tools (agent),
                       Apply Discount (tool)
        Synthesizer Agent → Synthesizer Agent Process (agent) → Synthesizer Reply (llm)
    """
    user_q = p["turn2_user"]
    sentiment = p["turn2_sentiment"]
    apply_out = _apply_output(p)

    in_tok = _TOK_SENTIMENT[0] + _TOK_REPLY[0]
    out_tok = _TOK_SENTIMENT[1] + _TOK_REPLY[1]
    # Turn-2 trace metadata mirrors runner._promo_trace_metadata's *apply* branch
    # (apply_status, the applied discount) + token totals.
    meta = {
        "discount_usd": _meta_num(p["discount_usd"]),
        "discount_pct": str(p["discount_pct"]),
        "list_price": _meta_num(p["list_price"]),
        "promo_expired": str(p["promo_expired"]).lower(),
        "apply_status": "201",
        "promo_code": p["promo_code"],
        "promo_end_date": p["promo_end_date"],
        "promo_last_updated_at": p["promo_last_updated_at"],
        "customer_sentiment": sentiment,
        "sentiment_score": _meta_num(_SENTIMENT_SCORE[sentiment]),
        "product_name": p["product_name"],
        "discount_tier": p["discount_tier"],
        "input_tokens": str(in_tok),
        "output_tokens": str(out_tok),
        "total_tokens": str(in_tok + out_tok),
    }
    logger.start_trace(
        input=_trace_state(user_q), name="ops_desk_run", created_at=t0, metadata=meta,
    )

    def at(s: float) -> datetime:
        return t0 + timedelta(seconds=s)

    # Router — runs but short-circuits (pending promo + "yes"), so no intent llm.
    logger.add_workflow_span(input=user_q, name="Router", created_at=at(0.02))
    logger.conclude(output="route=promo intent=promo_inquiry")  # pop Router → trace

    # Action Agent
    logger.add_workflow_span(input=user_q, name="Action Agent", created_at=at(0.20))
    logger.add_llm_span(
        input=user_q, output=sentiment, model="gpt-4o-mini",
        name="Classify Sentiment", created_at=at(0.25), duration_ns=180_000_000,
        num_input_tokens=_TOK_SENTIMENT[0], num_output_tokens=_TOK_SENTIMENT[1],
        total_tokens=sum(_TOK_SENTIMENT),
        metadata={"customer_sentiment": sentiment,
                  "sentiment_score": _meta_num(_SENTIMENT_SCORE[sentiment])},
    )
    logger.add_agent_span(
        input=json.dumps({"pending_promo": p["promo_code"], "affirmative": True}),
        output=json.dumps(["apply_discount"]), name="Determine Tools",
        created_at=at(0.30), duration_ns=1_000_000,
    )
    logger.conclude(output=json.dumps(["apply_discount"]))  # pop Determine Tools → Action
    logger.add_tool_span(
        input=json.dumps({"promo_code": p["promo_code"], "sku": p["sku"], "confirm": "yes"}),
        output=json.dumps(apply_out), name="Apply Discount", created_at=at(0.50),
        duration_ns=110_000_000, status_code=apply_out["status"],
        metadata=_tool_metadata(p),
    )
    logger.conclude(output=json.dumps(apply_out))  # pop Action Agent → trace

    # Synthesizer Agent → Process → Synthesizer Reply (llm, real token counts).
    reply = _reply_text(p)
    logger.add_workflow_span(
        input=json.dumps(apply_out), name="Synthesizer Agent", created_at=at(0.80),
    )
    logger.add_agent_span(
        input=json.dumps(apply_out), name="Synthesizer Agent Process",
        created_at=at(0.82),
    )
    logger.add_llm_span(
        input=json.dumps({"offer": _offer_label(p), "product": p["product_name"]}),
        output=reply, model="gpt-4o-mini", name="Synthesizer Reply",
        created_at=at(0.85), duration_ns=280_000_000,
        num_input_tokens=_TOK_REPLY[0], num_output_tokens=_TOK_REPLY[1],
        total_tokens=sum(_TOK_REPLY),
    )
    logger.conclude(output=reply)  # pop Process → Synthesizer Agent
    logger.conclude(output=reply)  # pop Synthesizer Agent → trace
    logger.conclude(output="completed", conclude_all=True)  # close the trace


def _inject_one(logger: GalileoLogger, p: Dict[str, Any], t0: datetime) -> None:
    """Emit one full conversation as TWO traces under one session, exactly like
    the live app (each chat turn is its own ``ops_desk_run`` trace)."""
    external_id = f"promo-{uuid.uuid4().hex[:12]}"
    logger.start_session(name="ops-desk:promo", external_id=external_id)

    _inject_turn1(logger, p, t0)
    # The customer takes a beat before confirming; keep the gap small so the two
    # traces stay adjacent in the time-ordered Console table.
    _inject_turn2(logger, p, t0 + timedelta(seconds=_TURN_GAP_S))


def inject_sessions(
    project: str,
    log_stream: str,
    *,
    mistakes_per_hour: float = 10.0,
    hours: float = 3.0,
    correct_per_hour: float = 6.0,
    seed: int = 7,
    flush_every: int = 20,
    window_minutes: Optional[float] = None,
    mistakes_last: bool = False,
    spread_days: float = 0.0,
    tz_name: str = "America/Los_Angeles",
) -> Dict[str, Any]:
    """Inject synthetic promo traces at a steady per-hour rate.

    Callable form of the CLI so the Ops-view "create demo project" button can
    reuse the exact same traffic. Roughly ``mistakes_per_hour`` MISTAKE sessions
    (expired $700 clearance applied) and ``correct_per_hour`` CORRECT sessions
    (live $200 student deal) are generated; the counts still come from
    ``mistakes_per_hour``/``correct_per_hour`` × ``hours``.

    Timestamp spread (three modes, in priority order):
    - ``spread_days`` > 0: spread the sessions across the last N days following
      realistic webstore seasonality (busier evenings/lunch, busier weekends) in
      ``tz_name`` — the "date-relevant, not all from one day" mode used by the
      Ops button.
    - ``window_minutes`` set: bunch everything into the last N minutes (top of
      the trace table).
    - otherwise: even spread across the last ``hours``.

    ``mistakes_last`` (only meaningful without ``spread_days``) gives the
    expired-promo sessions the newest timestamps so they surface at the top.
    """
    if not project or not log_stream:
        raise ValueError("project and log_stream are required")

    rng = random.Random(seed)
    random.seed(seed)

    hours = max(0.1, float(hours))
    n_mistakes = max(0, int(round(float(mistakes_per_hour) * hours)))
    n_correct = max(0, int(round(float(correct_per_hour) * hours)))

    if mistakes_last:
        # CORRECT (older) first, then MISTAKE (newest) — the expired-promo
        # spike lands at the top of the Console list, ordered by time desc.
        kinds: List[str] = ["correct"] * n_correct + ["mistake"] * n_mistakes
    else:
        # Interleave the two kinds and shuffle so mistakes are sprinkled through
        # the window rather than clumped at one end.
        kinds = ["mistake"] * n_mistakes + ["correct"] * n_correct
        rng.shuffle(kinds)
    n = len(kinds)
    if n == 0:
        raise ValueError("nothing to inject: mistakes_per_hour and correct_per_hour are both 0")

    # Pick turn-1 start timestamps (one per session, ascending).
    if spread_days and float(spread_days) > 0:
        # Date-relevant multi-day spread with realistic webstore seasonality.
        span_label = f"{float(spread_days):g}d seasonal ({tz_name})"
        starts = _seasonal_starts(n, float(spread_days), tz_name, rng)
    else:
        if window_minutes is not None:
            window = timedelta(minutes=max(0.0, float(window_minutes)))
            span_label = f"{float(window_minutes):g}m"
        else:
            window = timedelta(hours=hours)
            span_label = f"{hours:g}h"
        start = datetime.now(timezone.utc) - window
        # Reserve headroom for the intra-conversation gap so a turn-2 (apply)
        # trace never lands in the future: spread turn-1 starts over [start, now-gap].
        usable_s = max(1.0, window.total_seconds() - _TURN_GAP_S)
        step_s = usable_s / max(n, 1)
        starts = [
            start + timedelta(seconds=i * step_s + rng.uniform(0.0, step_s * 0.5))
            for i in range(n)
        ]

    logger = GalileoLogger(project=project, log_stream=log_stream)
    print(
        f"Injecting {n} promo conversations (2 traces each = {2 * n} traces) into "
        f"project={project!r} log_stream={log_stream!r} over {span_label} "
        f"(~{mistakes_per_hour:g} mistakes/h → {n_mistakes} expired, {n_correct} live"
        f"{'; mistakes on top' if mistakes_last else ''})"
    )

    leaked_total = 0.0
    expired_applied = 0
    for i, kind in enumerate(kinds):
        p = _plan_session(kind, rng)
        # ``starts`` is ascending; ``kinds`` is shuffled, so expired-promo
        # mistakes are sprinkled across the whole window rather than clumped.
        t0 = starts[i]
        _inject_one(logger, p, t0)

        if p["promo_expired"]:
            leaked_total += p["discount_usd"]
            expired_applied += 1

        if (i + 1) % flush_every == 0:
            logger.flush()
            print(f"  … flushed {i + 1}/{n}")

    logger.flush()
    console = os.environ.get("GALILEO_CONSOLE_URL", "").rstrip("/")
    print("\n✅ Done.")
    print(f"   expired promos applied: {expired_applied}")
    print(f"   leaked discount total : USD {leaked_total:,.2f}")
    return {
        "project": project,
        "log_stream": log_stream,
        "sessions": n,
        "traces": 2 * n,  # two ops_desk_run traces per conversation (search + apply)
        "mistakes_per_hour": mistakes_per_hour,
        "hours": hours,
        "expired_applied": expired_applied,
        "correct_applied": n_correct,
        "leaked_discount_usd": round(leaked_total, 2),
        "console_url": console or None,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Inject synthetic promo sessions into a Galileo log stream.")
    ap.add_argument("--project", default=os.environ.get("GALILEO_PROJECT"),
                    help="Galileo project (default: $GALILEO_PROJECT).")
    ap.add_argument("--log-stream", default=os.environ.get("GALILEO_LOG_STREAM"),
                    help="Galileo log stream (default: $GALILEO_LOG_STREAM).")
    ap.add_argument("--mistakes-per-hour", type=float, default=10.0,
                    help="Approx number of EXPIRED-promo mistakes to inject per hour.")
    ap.add_argument("--hours", type=float, default=3.0,
                    help="Spread sessions across this many hours ending 'now'.")
    ap.add_argument("--correct-per-hour", type=float, default=6.0,
                    help="Approx number of CORRECT (live $200) sessions per hour, for baseline.")
    ap.add_argument("--seed", type=int, default=7, help="RNG seed for reproducible ordering.")
    ap.add_argument("--flush-every", type=int, default=20, help="Flush to Galileo every N sessions.")
    ap.add_argument("--window-minutes", type=float, default=None,
                    help="Bunch all sessions into the last N minutes (overrides --hours spread) "
                         "so the batch lands at the top of the Console trace table.")
    ap.add_argument("--mistakes-last", action="store_true",
                    help="Give the expired-promo (positive-sentiment) sessions the newest "
                         "timestamps so the spike shows at the very top.")
    ap.add_argument("--spread-days", type=float, default=0.0,
                    help="Spread sessions across the last N DAYS with realistic webstore "
                         "seasonality (busier evenings/lunch + weekends). Overrides --hours/"
                         "--window-minutes spread. 0 = keep the last-N-hours behavior.")
    ap.add_argument("--tz", dest="tz_name", default="America/Los_Angeles",
                    help="Store timezone for the --spread-days day/night curve.")
    args = ap.parse_args()

    if not args.project or not args.log_stream:
        raise SystemExit(
            "Set --project and --log-stream (or GALILEO_PROJECT / GALILEO_LOG_STREAM). "
            "Create them in the Console first."
        )

    summary = inject_sessions(
        args.project,
        args.log_stream,
        mistakes_per_hour=args.mistakes_per_hour,
        hours=args.hours,
        correct_per_hour=args.correct_per_hour,
        seed=args.seed,
        flush_every=args.flush_every,
        window_minutes=args.window_minutes,
        mistakes_last=args.mistakes_last,
        spread_days=args.spread_days,
        tz_name=args.tz_name,
    )

    console = summary.get("console_url")
    if console:
        print(f"   Open the Console ({console}) → project {args.project!r} → log stream "
              f"{args.log_stream!r}, then 'Generate signal' on the 'Apply Discount' span "
              f"(promo_expired == 'true').")


if __name__ == "__main__":
    main()
