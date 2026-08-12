"""
Inject synthetic promo sessions straight into a Galileo log stream.

Each session is ONE trace containing a full "promo shopping" conversation:

    Classify Intent (llm)
      -> Check Promotions (tool)   -- surfaces a stale/expired promo
      -> Propose (llm)             -- agent offers the deal
      -> Apply Discount (tool)     -- APPLIES it; carries the $ + expiry metadata
      -> Reply (llm)               -- cheerful confirmation

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

Each MISTAKE session also carries a delighted customer reply and a high
``sentiment_score``, so customer sentiment spikes exactly where the discount
does — the "agent over-discounted to juice sentiment" story.

Mistakes are injected at a target rate (``--mistakes-per-hour``, default ~10),
spread across a ``--hours`` window ending now, so the timestamps line up as a
believable "N mistakes per hour" stream you can chart over time.

Metadata keys on the **Apply Discount** span match the live app
(``app/agents/action.py``) so a signal/eval built on this seeded data also fires
on real traffic:

  discount_usd (str), list_price (str), promo_code (str),
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
from typing import Any, Dict, List

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


def _money(value: float) -> str:
    """Human-readable money for reply text (with thousands separators)."""
    return f"{value:,.2f}"


def _meta_num(value: float) -> str:
    """Metadata money string WITHOUT separators, matching the live app's
    ``f"{float(x):.2f}"`` so a signal/eval fires identically on seeded and
    real traffic."""
    return f"{float(value):.2f}"


def _plan_session(kind: str, rng: random.Random) -> Dict[str, Any]:
    """Decide product + promo + dollar amount for a session of ``kind``.

    ``kind`` is ``"mistake"`` (applies the expired $700 QMobile deal — the leak)
    or ``"correct"`` (applies the live $200 Fall sale — the baseline). There's a
    single catalog product (the $1,000 phone), so every session is about it.

    Sentiment rides along with the discount: a MISTAKE ($700) session gets a
    delighted customer and a high ``sentiment_score``; a CORRECT ($200) session
    stays neutral. Charting sentiment then spikes exactly where the discount
    does — the anomaly the demo narrates.
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
        sentiment = "positive"
        sentiment_score = round(rng.uniform(0.88, 1.0), 2)
        customer_followup = (
            f"Whoa, {currency} {_money(discount)} off?! That's amazing — "
            f"thank you so much, you totally made my day!"
        )
    else:
        promo = LIVE_PROMO
        discount = round(min(LIVE_DISCOUNT_USD, list_price), 2)  # $200 off
        promo_expired = False
        end_date = (now + timedelta(days=30)).isoformat()
        # Freshly synced record.
        last_updated_at = (now - timedelta(days=1)).isoformat()
        discount_type = "fixed"
        sentiment = "neutral"
        sentiment_score = round(rng.uniform(0.45, 0.62), 2)
        customer_followup = "Okay, sounds good — go ahead and add it."

    final_price = round(max(list_price - discount, 0.0), 2)
    return {
        "product_name": product.product_name,
        "sku": product.sku,
        "currency": currency,
        "list_price": list_price,
        "discount_usd": discount,
        "final_price": final_price,
        "promo_code": promo["code"],
        "promo_description": promo["description"],
        "promo_end_date": end_date,
        "promo_expired": promo_expired,
        "promo_last_updated_at": last_updated_at,
        "discount_tier": promo["tier"],
        "discount_type": discount_type,
        "customer_sentiment": sentiment,
        "sentiment_score": sentiment_score,
        "customer_followup": customer_followup,
    }


def _tool_metadata(p: Dict[str, Any]) -> Dict[str, Any]:
    """Metadata for the Apply Discount span — string keys match the live app,
    plus a numeric key for charting."""
    return {
        "discount_usd": _meta_num(p["discount_usd"]),
        "list_price": _meta_num(p["list_price"]),
        "promo_code": p["promo_code"],
        "promo_expired": str(p["promo_expired"]).lower(),
        "promo_end_date": p["promo_end_date"],
        "promo_last_updated_at": p["promo_last_updated_at"],
        "discount_tier": p["discount_tier"],
        # Numeric copy so Console charts $ over time without string parsing.
        "discount_usd_num": float(p["discount_usd"]),
    }


def _apply_output(p: Dict[str, Any], blocked: bool) -> Dict[str, Any]:
    cur = p["currency"]
    if blocked:
        return {
            "status": 412,
            "error": "blocked_by_agent_control",
            "product_name": p["product_name"],
            "sku": p["sku"],
            "currency": cur,
            "list_price": p["list_price"],
            "discount_usd": 0.0,
            "final_price": p["list_price"],
            "attempted_discount_usd": p["discount_usd"],
            "promo_code": p["promo_code"],
            "promo_expired": True,
            "promo_end_date": p["promo_end_date"],
            "promo_last_updated_at": p["promo_last_updated_at"],
            "discount_tier": p["discount_tier"],
            "status_message": f"Blocked by Agent Control: promo {p['promo_code']} expired",
        }
    return {
        "status": 201,
        "cart_id": f"CART_{random.randint(10000, 99999)}",
        "product_name": p["product_name"],
        "sku": p["sku"],
        "currency": cur,
        "list_price": p["list_price"],
        "discount_usd": p["discount_usd"],
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


def _inject_one(logger: GalileoLogger, p: Dict[str, Any], t0: datetime, blocked: bool) -> None:
    cur = p["currency"]
    user_q = f"Any discount on the {p['product_name']}?"

    external_id = f"promo-{uuid.uuid4().hex[:12]}"
    logger.start_session(
        name=f"Promo chat · {p['product_name']}",
        external_id=external_id,
    )

    # Trace-level metadata is what the Console's trace-table column selector can
    # surface as columns. Values MUST be flat strings (Galileo requirement), so
    # `discount_usd` here is a comma-free numeric string you can enable as a
    # column and filter/sort as a number. Keys mirror runner._promo_trace_metadata
    # so seeded and live traces expose the same columns.
    applied_usd = 0.0 if blocked else p["discount_usd"]
    apply_status_code = 412 if blocked else 201
    promo_stage = "blocked" if blocked else "applied"
    trace_meta = {
        "promo_code": p["promo_code"],
        "promo_expired": str(p["promo_expired"]).lower(),
        "discount_usd": _meta_num(applied_usd),
        "list_price": _meta_num(p["list_price"]),
        "product_name": p["product_name"],
        "discount_tier": p["discount_tier"],
        "promo_end_date": p["promo_end_date"],
        "promo_last_updated_at": p["promo_last_updated_at"],
        "apply_status": str(apply_status_code),
        "promo_stage": promo_stage,
        "customer_sentiment": p["customer_sentiment"],
        "sentiment_score": _meta_num(p["sentiment_score"]),
        "blocked_by_control": str(blocked).lower(),
        # Token totals as trace-level columns, mirroring the live runner
        # (runner._token_trace_metadata) so injected + live rows share one
        # populated column. Sum of the four llm spans below: intent (48/3),
        # propose (180/60), sentiment (40/1), reply (160/55).
        "input_tokens": "428",
        "output_tokens": "119",
        "total_tokens": "547",
    }
    logger.start_trace(
        input=user_q,
        name="Promo conversation",
        created_at=t0,
        metadata=trace_meta,
        external_id=external_id,
    )

    def at(offset_s: float) -> datetime:
        return t0 + timedelta(seconds=offset_s)

    # 1) intent
    logger.add_llm_span(
        input=user_q,
        output="promo_inquiry",
        model="gpt-4o-mini",
        name="Classify Intent",
        created_at=at(0.2),
        duration_ns=200_000_000,
        num_input_tokens=48,
        num_output_tokens=3,
        total_tokens=51,
    )

    # 2) check promotions (surfaces the expired promo alongside a live one).
    # The live promo reads as freshly synced; the expired one carries an old
    # last_updated_at — the stale record whose expiry flag was never refreshed.
    _recent_iso = (t0 - timedelta(days=1)).isoformat()
    _stale_iso = (t0 - timedelta(days=60)).isoformat()
    check_out = {
        "product_name": p["product_name"],
        "sku": p["sku"],
        "currency": cur,
        "list_price": p["list_price"],
        "has_expired_promo": True,
        "promotions": [
            {"code": LIVE_PROMO["code"], "expired": False,
             "last_updated_at": _recent_iso, "discount_usd": LIVE_DISCOUNT_USD},
            {"code": EXPIRED_PROMO["code"], "expired": True,
             "last_updated_at": _stale_iso,
             "discount_usd": min(EXPIRED_DISCOUNT_USD, p["list_price"])},
        ],
        "proposed_promo_code": p["promo_code"],
        "proposed_discount_usd": p["discount_usd"],
        "proposed_promo_expired": p["promo_expired"],
    }
    logger.add_tool_span(
        input=json.dumps({"query": user_q, "sku": p["sku"]}),
        output=json.dumps(check_out),
        name="Check Promotions",
        created_at=at(0.5),
        duration_ns=120_000_000,
        status_code=200,
        metadata={
            "has_expired_promo": "true",
            "proposed_promo_code": p["promo_code"],
            "proposed_promo_expired": str(p["promo_expired"]).lower(),
        },
    )

    # 3) propose reply (turn 1). Pitch the offer by name (e.g. "QMobile partner
    # promotion"), not the raw code — QMobile is a promotional partner.
    offer = p["promo_description"].split(" — ", 1)[0].strip()
    propose = (
        f"Great news — Voltway is running the {offer} on the "
        f"{p['product_name']}, saving you {cur} {_money(p['discount_usd'])} and "
        f"bringing it to {cur} {_money(p['final_price'])}. "
        f"Want me to apply it and add it to your cart?"
    )
    logger.add_llm_span(
        input=json.dumps(check_out),
        output=propose,
        model="gpt-4o-mini",
        name="Synthesizer Propose",
        created_at=at(0.9),
        duration_ns=300_000_000,
        num_input_tokens=180,
        num_output_tokens=60,
        total_tokens=240,
    )

    # 3b) customer reacts, agent classifies sentiment. The delighted reaction to
    # a big (expired) discount is what makes sentiment spike alongside the leak.
    logger.add_llm_span(
        input=p["customer_followup"],
        output=p["customer_sentiment"],
        model="gpt-4o-mini",
        name="Classify Sentiment",
        created_at=at(1.1),
        duration_ns=180_000_000,
        num_input_tokens=40,
        num_output_tokens=1,
        total_tokens=41,
        metadata={
            "customer_sentiment": p["customer_sentiment"],
            "sentiment_score": _meta_num(p["sentiment_score"]),
        },
    )

    # 4) apply discount -- THE span the signal keys on
    apply_out = _apply_output(p, blocked)
    logger.add_tool_span(
        input=json.dumps({"promo_code": p["promo_code"], "sku": p["sku"], "confirm": "yes"}),
        output=json.dumps(apply_out),
        name="Apply Discount",
        created_at=at(1.4),
        duration_ns=110_000_000,
        status_code=apply_out["status"],
        metadata=_tool_metadata(p),
    )

    # 5) final reply
    if blocked:
        reply = (
            f"I'm sorry, but the {offer} has expired, so I wasn't able to "
            f"apply it — the {p['product_name']} stays at {cur} {_money(p['list_price'])}."
        )
    else:
        reply = (
            f"Good news — I applied the {offer} to the {p['product_name']}, "
            f"saving you {cur} {_money(p['discount_usd'])}. Your new price is "
            f"{cur} {_money(p['final_price'])}. I've added it to your cart."
        )
    logger.add_llm_span(
        input=json.dumps(apply_out),
        output=reply,
        model="gpt-4o-mini",
        name="Synthesizer Reply",
        created_at=at(1.9),
        duration_ns=280_000_000,
        num_input_tokens=160,
        num_output_tokens=55,
        total_tokens=215,
    )

    logger.conclude(output=reply, conclude_all=True)


def inject_sessions(
    project: str,
    log_stream: str,
    *,
    mistakes_per_hour: float = 10.0,
    hours: float = 3.0,
    correct_per_hour: float = 6.0,
    seed: int = 7,
    flush_every: int = 20,
) -> Dict[str, Any]:
    """Inject synthetic promo traces at a steady per-hour rate.

    Callable form of the CLI so the Ops-view "create demo project" button can
    reuse the exact same traffic. Roughly ``mistakes_per_hour`` MISTAKE sessions
    (expired $700 clearance applied) and ``correct_per_hour`` CORRECT sessions
    (live $200 student deal) are spread across the last ``hours`` and shuffled,
    so the timestamps read as a believable "~N mistakes per hour" stream.
    Returns a summary dict for the API response.
    """
    if not project or not log_stream:
        raise ValueError("project and log_stream are required")

    rng = random.Random(seed)
    random.seed(seed)

    hours = max(0.1, float(hours))
    n_mistakes = max(0, int(round(float(mistakes_per_hour) * hours)))
    n_correct = max(0, int(round(float(correct_per_hour) * hours)))

    # Interleave the two kinds and shuffle so mistakes are sprinkled through the
    # window rather than clumped at one end.
    kinds: List[str] = ["mistake"] * n_mistakes + ["correct"] * n_correct
    rng.shuffle(kinds)
    n = len(kinds)
    if n == 0:
        raise ValueError("nothing to inject: mistakes_per_hour and correct_per_hour are both 0")

    window = timedelta(hours=hours)
    start = datetime.now(timezone.utc) - window
    step_s = window.total_seconds() / max(n, 1)

    logger = GalileoLogger(project=project, log_stream=log_stream)
    print(
        f"Injecting {n} promo sessions into project={project!r} "
        f"log_stream={log_stream!r} over {hours:g}h "
        f"(~{mistakes_per_hour:g} mistakes/h → {n_mistakes} expired, {n_correct} live)"
    )

    leaked_total = 0.0
    expired_applied = 0
    for i, kind in enumerate(kinds):
        p = _plan_session(kind, rng)
        # Even spacing plus a little jitter so timestamps don't look robotic,
        # while staying inside the [start, now] window.
        jitter = rng.uniform(0.0, step_s * 0.5)
        t0 = start + timedelta(seconds=i * step_s + jitter)
        _inject_one(logger, p, t0, blocked=False)

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
    )

    console = summary.get("console_url")
    if console:
        print(f"   Open the Console ({console}) → project {args.project!r} → log stream "
              f"{args.log_stream!r}, then 'Generate signal' on the 'Apply Discount' span "
              f"(promo_expired == 'true').")


if __name__ == "__main__":
    main()
