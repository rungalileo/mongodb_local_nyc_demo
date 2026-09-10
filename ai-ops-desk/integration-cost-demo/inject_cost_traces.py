"""
Inject cheap, token-heavy LLM traces that mimic realistic webstore traffic — used
to drive the Console's *Integration costs → LLM Evaluator Costs* view.

Purpose
-------
The cost view attributes a dollar figure to each project, computed from the token
usage its enabled LLM-as-judge metrics consume × the evaluator model's configured
price. This script seeds a dummy project with subject traces spread across a
Jul→now window shaped like real store traffic (diurnal + weekly seasonality), so
the cost graph shows believable **weekend bumps** and an **evening/lunch ripple**
at hourly zoom — instead of one artificial spike.

The decoupling that makes this cheap
------------------------------------
Two independent dials:

  * TRACE COUNT   -> drives *real* eval spend (the org's LLM budget). Keep small.
  * MODEL PRICE   -> drives the *displayed* dollar number. Set in the Console UI,
                     free, and never touches your real bill.

So: run the judges on a cheap model (e.g. gpt-5-nano / gpt-4o-mini), inject a
modest number of traces, and inflate that model's *displayed* price to hit the
figure you want on screen. Real spend depends only on count × the cheap model's
real price; the inflated display price is pure cosmetics.

    CAVEAT — evaluators still run for real: injecting traces is free, but the
    enabled metrics score each one, consuming real evaluator tokens on the demo
    org budget (~$2-4 for 1,000 traces on gpt-4o-mini/gpt-5-nano; ~$52 on GPT-5).
    Point this at a project whose metrics run on a CHEAP model.

    CAVEAT — pricing is org-wide per model entry: to show two different prices
    (e.g. LLM-judge vs Luna) the two projects must use two DIFFERENT evaluator
    models. Inflating a model's price affects every project on that model.

Geometry to remember
--------------------
Over a ~50-day spread, peak_day_cost ≈ month_SUM / 33 (≈ effective days). A $1K
Sunday peak therefore implies a ~$33K month header — that's the honest cost of
spreading. Want a small month total? Use a shorter window or --event-day.

Two-project overlay (LLM-judge vs Luna)
---------------------------------------
Run twice with the SAME --seed / --start / --end / --tz / --traces so both
projects get byte-identical timestamps. The script prints the resolved --end;
pass that exact value on the second run (don't rely on the "now" default twice).

Usage
-----
Run with the app's venv (paths below assume you're in ``ai-ops-desk/``; the
script also works from any directory since it self-locates the package root):

    # dry run — print the traffic plan, peak day, price + real-spend estimates
    ./.venv/bin/python integration-cost-demo/inject_cost_traces.py \
        --dry-run --traces 1000 --num-metrics 5

    # inject into the LLM-judge project (enable its metrics on a CHEAP model first)
    ./.venv/bin/python integration-cost-demo/inject_cost_traces.py \
        --project "LLM-evals" --log-stream "Default" \
        --traces 1000 --num-metrics 5 --end "2026-08-20T15:00:00"

    # then the Luna project, SAME window -> identical timestamps for overlay
    ./.venv/bin/python integration-cost-demo/inject_cost_traces.py \
        --project "Luna-evals" --log-stream "Default" \
        --traces 1000 --num-metrics 5 --end "2026-08-20T15:00:00"

Requires the same Galileo env as the app (GALILEO_API_KEY, GALILEO_API_URL,
GALILEO_CONSOLE_URL) in ai-ops-desk/.env. Create the project + log stream in
the Console first. See README.md in this folder for the full walkthrough.
"""
from __future__ import annotations

import argparse
import json
import os
import random
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Runnable from anywhere: put the ai-ops-desk/ package root (this file's
# grandparent) on sys.path and load its .env explicitly, so `import app.*` and
# the Galileo creds resolve no matter what the current working directory is.
import sys

_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)
load_dotenv(os.path.join(_PKG_ROOT, ".env"))
import app.tls_trust  # noqa: F401  (trust the OS cert store / corp proxy)


# --------------------------------------------------------------------------- #
# Traffic-shape model
# --------------------------------------------------------------------------- #
# Relative interaction weight by LOCAL hour of day. Trough overnight, morning
# ramp, a lunch bump (~12-13), afternoon plateau, and the evening peak (~19-21)
# where a consumer webstore does most of its business, wind-down by midnight.
HOUR_WEIGHTS: Dict[int, float] = {
    0: 0.15, 1: 0.10, 2: 0.08, 3: 0.07, 4: 0.08, 5: 0.12,
    6: 0.25, 7: 0.45, 8: 0.70, 9: 0.90, 10: 1.00, 11: 1.10,
    12: 1.30, 13: 1.25, 14: 1.05, 15: 1.05, 16: 1.10, 17: 1.20,
    18: 1.45, 19: 1.60, 20: 1.65, 21: 1.45, 22: 1.00, 23: 0.55,
}

# Relative weight by weekday (Mon=0 … Sun=6). Weekends clearly busier; Friday
# leans up. This is what makes the daily-granularity chart show weekend bumps.
DOW_WEIGHTS: Dict[int, float] = {
    0: 0.90, 1: 0.90, 2: 0.90, 3: 0.95, 4: 1.10, 5: 1.55, 6: 1.50,
}

# Empirical calibration from a real run: $1,918.52 displayed at $220/1M (both
# fields) for 500 traces × 5 metrics ⇒ 8.72M eval tokens ⇒ ~3,480 eval tokens
# per metric-run. Used only for the price / real-spend ESTIMATES printed below.
CAL_EVAL_TOKENS_PER_METRIC = 3480
# Assumed input/output split of evaluator token usage (evaluators read a lot,
# emit a short verdict) — for the real-spend estimate only.
EVAL_INPUT_FRACTION = 0.80

# Real per-1M prices (input, output) for the real-spend estimate table.
REAL_MODEL_PRICES: Dict[str, Tuple[float, float]] = {
    "gpt-5": (1.25, 10.0),
    "gpt-5-mini": (0.25, 2.0),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-4o-mini": (0.15, 0.60),
}


# Realistic, benign support transcript used as the *subject* each LLM-as-judge
# metric scores. The evaluators read this TEXT, so its length drives eval-token
# usage per run. Kept clean/coherent so Correctness / Completeness / Instruction
# Adherence / Toxicity all have something sensible to grade.
_SUBJECT_INPUT = (
    "You are Voltway's customer support assistant. Follow policy, be concise, and "
    "confirm any account action before taking it.\n\n"
    "Customer: Hi, I ordered the YPhone 16 Pro Max last Tuesday and the tracking "
    "hasn't updated in four days. Order #A-48213. Can you tell me where it is and "
    "whether it'll arrive before the weekend? I need it for a trip on Saturday.\n"
    "Assistant: Thanks for the order number — let me pull up A-48213.\n"
    "Customer: Also, if it won't make it in time, can I change the shipping address "
    "to my office instead, or should I just cancel and reorder with express?\n"
    "Assistant: I can check the carrier status and, if it's still in the warehouse, "
    "update the address. Give me one moment.\n"
    "Customer: Great, thank you. And is the two-year warranty already active or do I "
    "need to register it separately once it arrives?"
)
_SUBJECT_OUTPUT = (
    "I found order A-48213. It shipped Wednesday and is currently at the regional "
    "carrier hub; the last scan was 18 hours ago, and estimated delivery is Friday, "
    "which should make your Saturday trip. Because it has already left our warehouse, "
    "I can't change the destination address directly, but I've filed a carrier "
    "redirect request to your office address on file — you'll get an email to confirm "
    "it within the hour. I did not cancel or reorder anything, since the current "
    "package is on track. Your two-year warranty activates automatically on delivery, "
    "so there's nothing to register. Is there anything else I can help with?"
)


def _build_body(repeats: int) -> Tuple[str, str]:
    """Subject input/output text, optionally lengthened by repeating the
    transcript block ``repeats`` times to raise eval-token usage per run."""
    r = max(1, int(repeats))
    sep = "\n\n--- (continued) ---\n\n"
    return sep.join([_SUBJECT_INPUT] * r), sep.join([_SUBJECT_OUTPUT] * r)


def _approx_tokens(text: str) -> int:
    """Rough token count (~4 chars/token) for cosmetic span stamps."""
    return max(1, len(text) // 4)


def _parse_dt(value: Optional[str], tz: ZoneInfo, *, end_of_now: bool) -> datetime:
    """Parse an ISO date/datetime as local ``tz``. ``None`` -> now (if
    ``end_of_now``) else start of today. Bare dates anchor to 00:00 local."""
    if not value:
        return datetime.now(tz) if end_of_now else datetime.combine(
            date.today(), time(0, 0), tzinfo=tz
        )
    raw = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        # date-only
        d = date.fromisoformat(raw)
        dt = datetime.combine(d, time(0, 0))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def _hour_buckets(start: datetime, end: datetime) -> List[datetime]:
    """Every hour boundary (local tz) from start (floored) up to and including
    the hour that contains ``end``."""
    cur = start.replace(minute=0, second=0, microsecond=0)
    buckets: List[datetime] = []
    while cur <= end:
        buckets.append(cur)
        cur += timedelta(hours=1)
    return buckets


def _plan_timestamps(
    start: datetime,
    end: datetime,
    traces: int,
    seed: int,
    event_day: Optional[date],
    event_mult: float,
) -> Tuple[List[datetime], Dict[date, int]]:
    """Distribute ``traces`` across the window following diurnal + weekly
    seasonality, returning UTC timestamps (sorted) and a per-day count map.

    Deterministic for a fixed (start, end, traces, seed, event_*): same inputs
    reproduce byte-identical timestamps, so two projects overlay exactly.
    """
    rng = random.Random(seed)
    buckets = _hour_buckets(start, end)
    if not buckets:
        return [], {}

    # 1) weight every hour bucket = hour-of-day × day-of-week × event × noise
    weights: List[float] = []
    for b in buckets:
        w = HOUR_WEIGHTS[b.hour] * DOW_WEIGHTS[b.weekday()]
        if event_day is not None and b.date() == event_day:
            w *= max(1.0, event_mult)
        w *= rng.uniform(0.85, 1.15)  # gentle per-hour noise
        weights.append(w)

    total_w = sum(weights) or 1.0

    # 2) expected fractional count per bucket -> integers via largest-remainder
    #    so the run hits ``traces`` exactly.
    exact = [w / total_w * traces for w in weights]
    counts = [int(x) for x in exact]
    remainder = traces - sum(counts)
    if remainder > 0:
        frac_order = sorted(
            range(len(exact)), key=lambda i: (exact[i] - counts[i]), reverse=True
        )
        for i in frac_order[:remainder]:
            counts[i] += 1

    # 3) place each trace at a random second within its hour (clamped to end)
    stamps_utc: List[datetime] = []
    per_day: Dict[date, int] = {}
    for b, c in zip(buckets, counts):
        if c <= 0:
            continue
        per_day[b.date()] = per_day.get(b.date(), 0) + c
        hour_end = min(b + timedelta(hours=1), end)
        span = max(1.0, (hour_end - b).total_seconds())
        for _ in range(c):
            ts_local = b + timedelta(seconds=rng.uniform(0, span))
            stamps_utc.append(ts_local.astimezone(timezone.utc))

    stamps_utc.sort()
    return stamps_utc, per_day


def _inject_one(
    logger,
    model: str,
    body_in: str,
    body_out: str,
    in_tok: int,
    out_tok: int,
    created_at: datetime,
) -> None:
    """One subject trace: a single chat.completion LLM span carrying a realistic
    support transcript. Enabled LLM-as-judge metrics read this TEXT — that's what
    generates evaluator token usage (and thus the cost). Stamped token numbers
    are cosmetic (they describe this app call, not the evaluators)."""
    logger.start_trace(
        input=body_in,
        name="agent_run",
        created_at=created_at,
        metadata={
            "input_tokens": str(in_tok),
            "output_tokens": str(out_tok),
            "total_tokens": str(in_tok + out_tok),
            "model": model,
        },
    )
    logger.add_llm_span(
        input=body_in,
        output=body_out,
        model=model,
        name="chat.completions",
        created_at=created_at,
        duration_ns=350_000_000,
        num_input_tokens=in_tok,
        num_output_tokens=out_tok,
        total_tokens=in_tok + out_tok,
    )
    logger.conclude(output=body_out, conclude_all=True)


def _print_estimates(
    traces: int,
    num_metrics: int,
    per_day: Dict[date, int],
) -> None:
    """Print the peak-day / SUM / display-price / real-spend estimates."""
    eval_tokens_per_trace = CAL_EVAL_TOKENS_PER_METRIC * max(1, num_metrics)
    total_eval_tokens = eval_tokens_per_trace * traces

    peak_day, peak_count = (max(per_day.items(), key=lambda kv: kv[1])
                            if per_day else (None, 0))
    avg_count = (sum(per_day.values()) / len(per_day)) if per_day else 0

    print("\nTraffic plan (diurnal + weekly seasonality):")
    print(json.dumps({
        "traces": traces,
        "days_covered": len(per_day),
        "avg_traces_per_day": round(avg_count, 1),
        "peak_day": str(peak_day) if peak_day else None,
        "peak_day_traces": peak_count,
        "metrics_assumed": num_metrics,
        "eval_tokens_per_trace": eval_tokens_per_trace,
        "approx_total_eval_tokens": total_eval_tokens,
    }, indent=2))

    # Displayed-price levers (set on the evaluator model, both input+output).
    print("\nDisplayed cost (set this price on the evaluator model, both fields):")
    for tgt in (500, 1000, 2000):
        if peak_count:
            price = tgt * 1_000_000.0 / (peak_count * eval_tokens_per_trace)
            month_sum = traces * eval_tokens_per_trace / 1_000_000.0 * price
            print(f"  peak day ≈ ${tgt:<5} -> price ≈ ${price:,.0f}/1M   "
                  f"(month SUM ≈ ${month_sum:,.0f})")

    # Real spend on the model that ACTUALLY runs the evals (independent of the
    # displayed price above).
    in_tok = total_eval_tokens * EVAL_INPUT_FRACTION
    out_tok = total_eval_tokens * (1 - EVAL_INPUT_FRACTION)
    print("\nReal eval spend for this batch (depends ONLY on the model you run on):")
    for name, (pi, po) in REAL_MODEL_PRICES.items():
        real = in_tok / 1_000_000.0 * pi + out_tok / 1_000_000.0 * po
        print(f"  {name:<12} (${pi}/${po} per 1M) -> ~${real:,.2f}")


def inject_cost_traces(
    project: str,
    log_stream: str,
    *,
    model: str = "gpt-4o",
    traces: int = 1000,
    body_repeats: int = 1,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    tz_name: str = "America/Los_Angeles",
    event_day: Optional[str] = None,
    event_mult: float = 1.0,
    seed: int = 7,
    flush_every: int = 25,
    num_metrics: int = 5,
    dry_run: bool = False,
) -> Dict[str, object]:
    if not project or not log_stream:
        raise ValueError("project and log_stream are required")

    tz = ZoneInfo(tz_name)
    start_dt = _parse_dt(start, tz, end_of_now=False) if start else _parse_dt(
        "2026-07-01", tz, end_of_now=False
    )
    end_dt = _parse_dt(end, tz, end_of_now=True)
    if end_dt <= start_dt:
        raise ValueError(f"end ({end_dt}) must be after start ({start_dt})")
    ev_day = date.fromisoformat(event_day) if event_day else None

    # The subject transcript the evaluators read; length (× body_repeats) drives
    # eval-token usage per run.
    body_in, body_out = _build_body(body_repeats)
    in_tok = int(input_tokens) if input_tokens is not None else _approx_tokens(body_in)
    out_tok = int(output_tokens) if output_tokens is not None else _approx_tokens(body_out)

    stamps, per_day = _plan_timestamps(start_dt, end_dt, traces, seed, ev_day, event_mult)

    print(f"Window: {start_dt.isoformat()}  ->  {end_dt.isoformat()}  ({tz_name})")
    print(f"Resolved --end (pass this exact value on the 2nd project for an "
          f"identical overlay):\n  --end \"{end_dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\"")
    _print_estimates(traces, num_metrics, per_day)

    if dry_run:
        print("\n(dry run — nothing sent)")
        return {"project": project, "log_stream": log_stream, "dry_run": True,
                "traces": traces, "days": len(per_day)}

    from galileo.logger.logger import GalileoLogger

    # Bind the logger to the *ids* of the names we were given. Critical when the
    # host process has GALILEO_PROJECT_ID / GALILEO_LOG_STREAM_ID set (the app's
    # live-target repointing does this): GalileoLogger resolves
    # ``project_id = project_id_arg or GALILEO_PROJECT_ID`` and, when an id is
    # present, SKIPS name resolution — so passing only ``project=<name>`` would
    # be silently ignored and every trace would land in the app's active project
    # (e.g. volt-assistant) instead of the one requested here. Resolving +
    # passing ids makes the target explicit and immune to those env vars.
    project_id = log_stream_id = None
    try:
        from galileo.projects import Projects
        from galileo.log_streams import LogStreams

        _proj = Projects().get(name=project)
        if _proj is not None:
            project_id = str(_proj.id)
            _ls = LogStreams().get(name=log_stream, project_id=project_id)
            if _ls is not None:
                log_stream_id = str(_ls.id)
    except Exception:
        # Best-effort: fall back to name-based binding (correct whenever the env
        # ids aren't set, e.g. plain CLI usage).
        project_id = log_stream_id = None

    logger = GalileoLogger(
        project=project,
        log_stream=log_stream,
        project_id=project_id,
        log_stream_id=log_stream_id,
    )
    print(f"\nInjecting {len(stamps)} subject traces into project={project!r} "
          f"log_stream={log_stream!r}…")

    for i, ts in enumerate(stamps):
        _inject_one(logger, model, body_in, body_out, in_tok, out_tok, ts)
        if (i + 1) % flush_every == 0:
            logger.flush()
            print(f"  … flushed {i + 1}/{len(stamps)}")

    logger.flush()
    console = os.environ.get("GALILEO_CONSOLE_URL", "").rstrip("/")
    print("\n✅ Done injecting subjects. Injection itself is $0 of API spend.")
    print("   Enabled LLM-as-judge metrics now run over these traces "
          "(that eval usage is what the cost graph prices).")
    print(f"   Check the cost graph for project {project!r}"
          + (f" at {console}" if console else ""))
    print("   Then set the evaluator model's price (see the estimates above).")
    return {"project": project, "log_stream": log_stream, "dry_run": False,
            "traces": len(stamps), "days": len(per_day)}


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Inject seasonal webstore traffic to drive an Integration Costs graph."
    )
    ap.add_argument("--project", default=os.environ.get("GALILEO_PROJECT", "LLM-evals"))
    ap.add_argument("--log-stream", default=os.environ.get("GALILEO_LOG_STREAM", "Default"))
    ap.add_argument("--model", default="gpt-4o",
                    help="model stamped on the subject span (cosmetic; NOT the evaluator model)")
    ap.add_argument("--traces", type=int, default=1000, help="total traces across the whole window")
    ap.add_argument("--body-repeats", type=int, default=1,
                    help="repeat the subject transcript N times to raise eval-token usage per run")
    ap.add_argument("--num-metrics", type=int, default=5,
                    help="how many LLM-as-judge metrics you enabled (for the estimates only)")
    ap.add_argument("--input-tokens", type=int, default=None, help="override cosmetic per-trace input token stamp")
    ap.add_argument("--output-tokens", type=int, default=None, help="override cosmetic per-trace output token stamp")
    ap.add_argument("--start", default="2026-07-01",
                    help="window start (ISO date/datetime, local --tz). Default 2026-07-01")
    ap.add_argument("--end", default=None,
                    help="window end (ISO date/datetime; 'Z'/offset honored, else local --tz). "
                         "Default = now. Pass the SAME value on the 2nd project for an identical overlay.")
    ap.add_argument("--tz", dest="tz_name", default="America/Los_Angeles",
                    help="store timezone for the day/night curve (default America/Los_Angeles)")
    ap.add_argument("--event-day", default=None,
                    help="optional ISO date to boost (e.g. a sale day) for a dramatic single-day spike")
    ap.add_argument("--event-mult", type=float, default=1.0,
                    help="multiplier applied to --event-day traffic (e.g. 4.0)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--flush-every", type=int, default=25)
    ap.add_argument("--dry-run", action="store_true", help="print the plan/estimates without sending")
    return ap.parse_args()


if __name__ == "__main__":
    a = _parse_args()
    inject_cost_traces(
        a.project,
        a.log_stream,
        model=a.model,
        traces=a.traces,
        body_repeats=a.body_repeats,
        input_tokens=a.input_tokens,
        output_tokens=a.output_tokens,
        start=a.start,
        end=a.end,
        tz_name=a.tz_name,
        event_day=a.event_day,
        event_mult=a.event_mult,
        seed=a.seed,
        flush_every=a.flush_every,
        num_metrics=a.num_metrics,
        dry_run=a.dry_run,
    )
