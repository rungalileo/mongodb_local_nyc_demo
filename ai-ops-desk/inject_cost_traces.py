"""
Inject cheap, token-heavy LLM traces to fake an "Integration Costs" spike.

Purpose
-------
The Console's *Integration costs → LLM Evaluator Costs* view attributes a dollar
figure to each project. This script seeds a dedicated dummy project (default
``LLM-evals``) with a batch of traces whose LLM spans carry very large token
counts, attributed to an expensive model (default ``gpt-4o``). If the cost view
is computed from the token usage we log on spans (× the model's standard price),
this makes the project's cost read in the **thousands** — as a demo prop.

Why this costs $0 in real money
--------------------------------
``GalileoLogger`` only *records* span objects; it never calls an LLM. The token
numbers below are literals we hand to the logger, so you can stamp millions of
tokens per span at zero real API spend and without touching Model pricing.

    CAVEAT — evaluators: injecting traces is free, BUT if the target project has
    an auto-run LLM-as-judge metric enabled on its log stream, those injected
    traces will trigger real evaluator runs (which draw on the demo org's LLM
    budget, not your personal bill). For the pure "fake cost, spend nothing"
    calibration, point this at a project/log stream with NO auto-run metric.

Calibration-first
-----------------
Run a small batch, then check the project's cost graph:
  * If the number moved with the logged tokens -> scale up ``--target-usd`` /
    ``--traces`` to hit your figure. Done: no pricing edits, no eval spend.
  * If it did NOT move -> the graph counts only metered evaluator runs, so the
    only levers are (a) real eval runs on an expensive model, or (b) inflating
    Model pricing for a *dedicated* model entry scoped to this project.

Usage
-----
    # dry run — print the plan + the price you'd set to hit ~$1k/$2.5k/$5k
    python inject_cost_traces.py --dry-run --traces 100 --num-metrics 5

    # real injection of subject traces into the LLM-evals project (enable the
    # LLM-as-judge metrics in the Console FIRST so they score these on arrival)
    python inject_cost_traces.py --project "LLM-evals" --log-stream "Default" \
        --traces 100 --body-repeats 1 --num-metrics 5 --hours 24 --spike

Requires the same Galileo env as the app (GALILEO_API_KEY, GALILEO_API_URL,
GALILEO_CONSOLE_URL). Create the project + log stream in the Console first.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()
import app.tls_trust  # noqa: F401  (trust the OS cert store / corp proxy)


# Realistic, benign support transcript used as the *subject* each LLM-as-judge
# metric scores. The evaluators read this TEXT (not the token numbers stamped on
# the span), so its length is what drives eval-token usage — and therefore the
# cost the graph attributes to this project. Scale it with --body-repeats to
# raise eval tokens per run (so the price you set can be more modest). Kept clean
# and coherent so Correctness / Completeness / Instruction Adherence / Toxicity
# all have something sensible to grade.
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


def _parse_end_time(end_time: Optional[str]) -> datetime:
    """Anchor for the window's end. ``None`` -> now (UTC). An ISO-8601 string is
    parsed and treated as UTC when it has no timezone, so passing the first
    project's newest-trace time reproduces the same timestamps."""
    if not end_time:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(str(end_time).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _created_at(start: datetime, window: timedelta, frac: float, spike: bool) -> datetime:
    # spike: skew timestamps toward the recent end so the cost graph rises to a
    # peak (frac**0.35 pushes most points near 1.0 = now).
    f = frac ** 0.35 if spike else frac
    return start + timedelta(seconds=window.total_seconds() * f)


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
    support transcript. The enabled LLM-as-judge metrics read this TEXT — that's
    what generates the evaluator token usage (and thus the cost). The stamped
    token numbers are cosmetic (they describe this app call, not the evaluators)."""
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


def inject_cost_traces(
    project: str,
    log_stream: str,
    *,
    model: str = "gpt-4o",
    traces: int = 100,
    body_repeats: int = 1,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    hours: float = 24.0,
    spike: bool = True,
    seed: int = 7,
    flush_every: int = 20,
    num_metrics: int = 5,
    end_time: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, object]:
    if not project or not log_stream:
        raise ValueError("project and log_stream are required")

    # The subject transcript the evaluators read. Its length (scaled by
    # body_repeats) drives eval-token usage per metric run — the real cost lever.
    body_in, body_out = _build_body(body_repeats)
    # Cosmetic span stamps: default to the actual body length; override if given.
    in_tok = int(input_tokens) if input_tokens is not None else _approx_tokens(body_in)
    out_tok = int(output_tokens) if output_tokens is not None else _approx_tokens(body_out)

    # Estimate eval-token usage so you can size the price: each enabled LLM metric
    # reads ~the whole trace once per trace. This is what the cost graph prices.
    eval_tokens_per_run = _approx_tokens(body_in) + _approx_tokens(body_out)
    total_eval_tokens = eval_tokens_per_run * traces * max(1, num_metrics)
    plan = {
        "project": project,
        "log_stream": log_stream,
        "subject_model": model,
        "traces": traces,
        "body_repeats": body_repeats,
        "enabled_metrics_assumed": num_metrics,
        "eval_tokens_per_run": eval_tokens_per_run,
        "eval_runs": traces * max(1, num_metrics),
        "approx_total_eval_tokens": total_eval_tokens,
    }
    print("Plan (cost comes from the enabled LLM-as-judge metrics, not these traces):")
    print(json.dumps(plan, indent=2))
    for tgt in (1000, 2500, 5000):
        rate = tgt / (total_eval_tokens / 1_000_000.0) if total_eval_tokens else 0
        print(f"  to show ~${tgt}: set the evaluator model price ≈ ${rate:,.0f} / 1M tokens")

    if dry_run:
        print("\n(dry run — nothing sent)")
        return {"project": project, "log_stream": log_stream, "dry_run": True, **plan}

    from galileo.logger.logger import GalileoLogger

    rng = random.Random(seed)
    window = timedelta(hours=max(0.1, float(hours)))
    # Anchor the window's END. Pass --end-time (the newest trace time from the
    # first project) with the SAME seed/traces/hours/spike to reproduce identical
    # timestamps for a one-on-one overlay; otherwise anchor to now.
    anchor = _parse_end_time(end_time)
    start = anchor - window

    logger = GalileoLogger(project=project, log_stream=log_stream)
    print(
        f"\nInjecting {traces} subject traces into project={project!r} "
        f"log_stream={log_stream!r} over {hours:g}h ending {anchor.isoformat()}"
        f"{' (spiked recent)' if spike else ''}…"
    )

    for i in range(traces):
        frac = (i + rng.uniform(0.0, 0.9)) / max(1, traces)
        ts = _created_at(start, window, min(1.0, frac), spike)
        _inject_one(logger, model, body_in, body_out, in_tok, out_tok, ts)
        if (i + 1) % flush_every == 0:
            logger.flush()
            print(f"  … flushed {i + 1}/{traces}")

    logger.flush()
    console = os.environ.get("GALILEO_CONSOLE_URL", "").rstrip("/")
    print("\n✅ Done injecting subjects. Injection itself is $0 of API spend.")
    print("   Your enabled LLM-as-judge metrics now run over these traces "
          "(that eval usage is what the cost graph prices).")
    print(f"   Check the cost graph for project {project!r}"
          + (f" at {console}" if console else ""))
    print("   Then set the evaluator model's price (see the ~$ estimates above).")
    return {"project": project, "log_stream": log_stream, "dry_run": False, **plan}


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Inject token-heavy traces to fake an Integration Costs spike.")
    ap.add_argument("--project", default=os.environ.get("GALILEO_PROJECT", "LLM-evals"))
    ap.add_argument("--log-stream", default=os.environ.get("GALILEO_LOG_STREAM", "Default"))
    ap.add_argument("--model", default="gpt-4o", help="model stamped on the subject span (cosmetic; NOT the evaluator model)")
    ap.add_argument("--traces", type=int, default=100)
    ap.add_argument("--body-repeats", type=int, default=1,
                    help="repeat the subject transcript N times to raise eval-token usage per run")
    ap.add_argument("--num-metrics", type=int, default=5,
                    help="how many LLM-as-judge metrics you enabled (for the price estimate only)")
    ap.add_argument("--input-tokens", type=int, default=None, help="override cosmetic per-trace input token stamp")
    ap.add_argument("--output-tokens", type=int, default=None, help="override cosmetic per-trace output token stamp")
    ap.add_argument("--hours", type=float, default=24.0, help="spread traces across the last N hours")
    ap.add_argument("--end-time", default=None,
                    help="ISO-8601 UTC anchor for the window END (e.g. 2026-08-18T19:05:00Z). "
                         "Pass the first project's newest-trace time + same seed/traces/hours to "
                         "reproduce identical timestamps. Defaults to now.")
    ap.add_argument("--spike", dest="spike", action="store_true", help="(default) skew timestamps recent so the graph peaks")
    ap.add_argument("--no-spike", dest="spike", action="store_false", help="spread evenly instead of peaking recent")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--flush-every", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true", help="print the plan/estimate without sending")
    ap.set_defaults(spike=True)
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
        hours=a.hours,
        spike=a.spike,
        seed=a.seed,
        flush_every=a.flush_every,
        num_metrics=a.num_metrics,
        end_time=a.end_time,
        dry_run=a.dry_run,
    )
