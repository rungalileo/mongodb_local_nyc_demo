#!/usr/bin/env python3
"""
Promo-traffic generator for the expired-promo demo.

Runs the promo scenarios in a loop from a single long-lived process so the
discount "spike" schedule is anchored to one start time. The applied discount
(logged as ``discount_usd`` span metadata) stays small for the first
``--normal-window`` minutes, then spikes — making the anomaly obvious when you
plot discount amounts over time in the Galileo trace view.

Examples
--------
    # Default: ~20s between runs, spike after 10 minutes, run until Ctrl+C
    python run_promo_traffic.py

    # Faster demo: spike after 2 minutes, a run every 10s, stop after 6 min
    python run_promo_traffic.py --normal-window 2 --interval 10 --duration 6

    # Send to a dedicated log stream
    python run_promo_traffic.py --log-stream promo-demo-1
"""
import argparse
import os
import time

# IMPORTANT: set schedule/env BEFORE importing anything that imports
# app.promo_spike (it reads PROMO_NORMAL_WINDOW_SECONDS at import time) or the
# Galileo logger (it reads GALILEO_LOG_STREAM at import time).
from dotenv import load_dotenv

load_dotenv(override=True)


PROMO_SCENARIOS = ["promo_oled_tv", "promo_laptop"]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Expired-promo traffic generator")
    parser.add_argument("--interval", type=float, default=20.0,
                        help="Seconds between runs (default: 20)")
    parser.add_argument("--normal-window", type=float, default=10.0,
                        help="Minutes of normal discounts before the spike (default: 10)")
    parser.add_argument("--duration", type=float, default=0.0,
                        help="Stop after this many minutes (0 = run until Ctrl+C)")
    parser.add_argument("--log-stream", type=str, default=None,
                        help="Override GALILEO_LOG_STREAM for this run")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    # Anchor the spike schedule to now and configure the normal window.
    start_epoch = time.time()
    os.environ["PROMO_TRAFFIC_START_EPOCH"] = str(start_epoch)
    os.environ["PROMO_NORMAL_WINDOW_SECONDS"] = str(int(args.normal_window * 60))
    if args.log_stream:
        os.environ["GALILEO_LOG_STREAM"] = args.log_stream

    # Import after env is set so promo_spike/galileo pick up the config.
    import asyncio

    from app.runner import run_query
    from app.scenarios import SCENARIOS
    from app.promo_spike import in_spike_window, elapsed_seconds
    from app.agent_control_setup import shutdown_agent_control

    log_stream = os.environ.get("GALILEO_LOG_STREAM", "(default)")
    print("=" * 60)
    print("Expired-promo traffic generator")
    print("=" * 60)
    print(f"Log stream:     {log_stream}")
    print(f"Interval:       {args.interval}s between runs")
    print(f"Normal window:  {args.normal_window} min, then discounts spike")
    print(f"Duration:       {'until Ctrl+C' if args.duration <= 0 else f'{args.duration} min'}")
    print("=" * 60)

    async def _run() -> None:
        count = 0
        try:
            while True:
                if args.duration > 0 and elapsed_seconds() >= args.duration * 60:
                    print("\nReached configured duration; stopping.")
                    break

                scenario = PROMO_SCENARIOS[count % len(PROMO_SCENARIOS)]
                query = SCENARIOS[scenario]
                phase = "SPIKE" if in_spike_window() else "normal"
                count += 1
                print(
                    f"\n[{count:04d}] t+{elapsed_seconds():6.0f}s  phase={phase:6s}  "
                    f"scenario={scenario}"
                )
                try:
                    result = await run_query(
                        user_query=query["user_query"],
                        user_id=query["user_id"],
                        toggles=[],
                        scenario=scenario,
                    )
                    action = result.get("action_output")
                    if action is not None:
                        for receipt in action.tool_receipts:
                            if receipt.tool == "apply_discount":
                                resp = receipt.response or {}
                                print(
                                    f"        applied {resp.get('promo_code')} "
                                    f"-{resp.get('currency')} {resp.get('discount_usd')} "
                                    f"(expired={resp.get('promo_expired')})"
                                )
                except Exception as e:  # noqa: BLE001
                    print(f"        ⚠️  run failed: {e}")

                time.sleep(args.interval)
        finally:
            await shutdown_agent_control()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\nStopped by user.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
