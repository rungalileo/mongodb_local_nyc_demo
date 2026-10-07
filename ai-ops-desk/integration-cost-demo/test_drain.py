"""Assertions for the scoring-drain logic in app/cost_demo_provision.py.

No network, no Galileo calls — ``_window_cost`` is replaced with canned series.
Run from ``ai-ops-desk/``:

    ./.venv/bin/python integration-cost-demo/test_drain.py

Why this exists
---------------
The cost demo changes an ORG-WIDE model price between phases, and each trace's
cost freezes at the price that was live when its evaluators finished. So the job
must not move the price while anything is still scoring. Getting that wrong does
not raise — it silently misprices a curve, and the only symptom is a chart at the
wrong level, noticed days later. These cases pin the two ways it went wrong:

  * exiting on a lull (two equal reads) instead of a drained queue
  * accepting a percentage tolerance, which a steadily-rising cost satisfies
    once 1% of the total exceeds the per-read increment
"""
import os
import sys

os.environ.setdefault("GALILEO_API_URL", "http://unused")
os.environ.setdefault("GALILEO_API_KEY", "unused")
os.environ["COST_DEMO_POLL_SECONDS"] = "1"
os.environ["COST_DEMO_STABLE_READS"] = "3"
os.environ["COST_DEMO_MIN_SETTLE_SECONDS"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app.cost_demo_provision as m  # noqa: E402

step = {"label": "t", "status": "running", "detail": ""}
calls = {"n": 0}


def series_reader(series):
    """Replace _window_cost with one that walks ``series``, holding the last."""
    calls["n"] = 0

    def read(client, pid, s, e):
        v = series[min(calls["n"], len(series) - 1)]
        calls["n"] += 1
        return float(v)

    return read


failures = []


def check(label, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


# 1) Burst with a mid-stream lull. The old heuristic stopped at the 100/100 pair
#    and changed the price with $200 of scoring still queued.
m.SCORING_TIMEOUT_SECONDS = 15
m._window_cost = series_reader([0, 100, 100, 250, 300, 300, 300, 300, 300, 300])
total, settled = m._poll_scoring(None, "p", "s", "e", step)
check("rides through a lull to the real total", settled and total == 300.0,
      f"total=${total:,.0f} settled={settled} reads={calls['n']}")

# 2) A steady climb must never read as settled.
m.SCORING_TIMEOUT_SECONDS = 4
m._window_cost = series_reader([100 + 50 * i for i in range(40)])
total, settled = m._poll_scoring(None, "p", "s", "e", step)
check("reports giving up on a steady climb", settled is False, f"total=${total:,.0f}")

# 3) A window stuck at $0 is scoring that has not started.
m._window_cost = lambda c, p, s, e: 0.0
total, settled = m._poll_scoring(None, "p", "s", "e", step)
check("does not treat $0 as drained", settled is False)

# 4) Sub-epsilon jitter is quiet, so API rounding cannot stall the job forever.
m.SCORING_TIMEOUT_SECONDS = 15
m._window_cost = series_reader([500.00, 500.20, 499.90, 500.10, 500.00, 500.05])
total, settled = m._poll_scoring(None, "p", "s", "e", step)
check("ignores cent-level jitter", settled is True, f"total=${total:,.2f}")

# 5) Pre-flight idle check: quiet only once BOTH projects are quiet.
ready = [{"name": "LLM_Evals", "project_id": "a"}, {"name": "Luna_Evals", "project_id": "b"}]
idx = {"a": 0, "b": 0}
moves = {"a": [10] * 12, "b": [5, 9, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14]}


def per_project(client, pid, s, e):
    v = moves[pid][min(idx[pid], len(moves[pid]) - 1)]
    idx[pid] += 1
    return float(v)


m.IDLE_TIMEOUT_SECONDS = 15
m._window_cost = per_project
check("waits for the slower project", m._wait_for_idle_scoring(None, ready, step) is True)

# 6) If one project never goes quiet the pre-flight must fail, so the caller
#    warns instead of silently mispricing an earlier run's leftovers.
idx = {"a": 0, "b": 0}
moves = {"a": [10] * 40, "b": [5 * i for i in range(40)]}
m.IDLE_TIMEOUT_SECONDS = 4
m._window_cost = per_project
check("fails pre-flight when scoring never stops",
      m._wait_for_idle_scoring(None, ready, step) is False)

print()
if failures:
    print(f"{len(failures)} failed: " + ", ".join(failures))
    sys.exit(1)
print("all assertions passed")
