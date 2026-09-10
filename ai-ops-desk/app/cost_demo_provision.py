"""One-click provisioning for the Integration-cost demo (LLM_Evals vs Luna_Evals).

Powers the Ops-view "Extend cost graph" button. It continues the two cost curves
from wherever they currently drop to $0 up to now, reproducing the dramatic
expensive-LLM-judge (~$1,830/1M) vs cheap-Luna (~$80/1M) contrast on the
Console's *Integration costs → LLM Evaluator Costs* view — from the app itself,
so the operator no longer has to run the scripts by hand.

Why it must be a phased, long-running job
-----------------------------------------
Both projects' metrics score on the SAME evaluator model (``gpt-5-nano``),
pricing is org-wide per model, and each trace's cost is FROZEN at scoring time.
So we cannot show two different prices at once — we sequence:

  Phase 1: set gpt-5-nano -> $1,830, inject LLM_Evals, poll until it scores.
  Phase 2: set gpt-5-nano -> $80,    inject Luna_Evals (identical timestamps),
           poll until it scores.
  Finally: remove the override so the real default returns (protects any live
           project — e.g. volt-assistant — that also scores on gpt-5-nano).

Because that takes several minutes, it runs in a background thread and the
drawer polls ``get_cost_demo_status()``.

Self-heal
---------
If either project / log stream was deleted, it is recreated and the captured
metrics (org-level scorers, so they survive project deletion) are re-enabled by
their scorer ids before injection.
"""
from __future__ import annotations

import importlib.util
import os
import threading
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

# Reuse the promo demo's idempotent project/stream helpers so behavior matches.
from app.promo_demo_provision import _ensure_project, _ensure_log_stream

# ---- Captured live configuration (snapshot 2026-09-10) --------------------
# Scorer ids are ORG-level and survive project deletion, so recreating a project
# only needs to re-enable these ids on its Default log stream.
EVAL_MODEL = os.getenv("COST_DEMO_EVAL_MODEL", "gpt-5-nano")
LOG_STREAM_NAME = os.getenv("COST_DEMO_LOG_STREAM", "Default")
DEFAULT_TZ = os.getenv("COST_DEMO_TZ", "America/Los_Angeles")

# Traffic density and bounds. ~20 traces/day matches the existing curve; the cap
# bounds real evaluator spend (a few $ per 1k traces on gpt-5-nano).
TRACES_PER_DAY = float(os.getenv("COST_DEMO_TRACES_PER_DAY", "20"))
MAX_TRACES = int(os.getenv("COST_DEMO_MAX_TRACES", "1000"))
SEED = int(os.getenv("COST_DEMO_SEED", "7"))
FALLBACK_BACKFILL_DAYS = 14  # used only if a project has NO existing cost data

# Scoring is async; poll the cost graph until the window total plateaus.
POLL_SECONDS = int(os.getenv("COST_DEMO_POLL_SECONDS", "20"))
SCORING_TIMEOUT_SECONDS = int(os.getenv("COST_DEMO_SCORING_TIMEOUT", "600"))

PROJECT_SPECS: List[Dict[str, Any]] = [
    {
        "name": "LLM_Evals",
        "price": float(os.getenv("COST_DEMO_LLM_PRICE", "1830")),
        "scorers": [
            ("3152f53d-aa2b-498e-a54b-87761460b51c", "Completeness - LLM"),
            ("e2faa132-d8a3-4625-af92-df26e62dcdda", "Input Toxicity - LLM"),
            ("c1c3810a-01c3-40e5-ab8b-930c905ab786", "Instruction Adherence - LLM"),
            ("8f860cb8-41dc-4467-b885-0b37d3fa4275", "Output Toxicity - LLM"),
            ("61a25589-7309-44bf-8a7c-64ea7a05219f", "Correctness-LLM"),
        ],
    },
    {
        "name": "Luna_Evals",
        "price": float(os.getenv("COST_DEMO_LUNA_PRICE", "80")),
        "scorers": [
            ("3bfa2b00-501c-48f7-873a-4fea1b49cca6", "Completeness - Luna v2"),
            ("91f451a8-8ce1-47b6-b1c4-d2fd94882119", "Correctness-Luna v2"),
            ("2f672e70-7d5f-485d-a52f-4f8d50362085", "Input Toxicity - Luna v2"),
            ("90484133-91ee-4b7f-b39a-159b0ed5d15d", "Instruction Adherence - Luna v2"),
            ("4fb7a0bb-84ac-4d39-b6f7-1277aa3b24ef", "Output Toxicity - Luna v2"),
        ],
    },
]

_ISO = "%Y-%m-%dT%H:%M:%SZ"

# Real demo projects that the delete helper must NEVER remove. Test runs use
# throwaway project names, which are deletable; these two are protected.
PROTECTED_PROJECTS = {s["name"] for s in PROJECT_SPECS}


# --------------------------------------------------------------------------- #
# Job state (single background run at a time)
# --------------------------------------------------------------------------- #
_LOCK = threading.Lock()
_JOB: Dict[str, Any] = {"state": "idle"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime(_ISO)


def _reset_job() -> None:
    _JOB.clear()
    _JOB.update(
        {
            "state": "running",
            "phase": None,
            "started_at": _now_iso(),
            "finished_at": None,
            "error": None,
            "window": None,
            "steps": [],
            "summary": None,
        }
    )


def _add_step(label: str, status: str, detail: str = "") -> Dict[str, Any]:
    step = {"label": label, "status": status, "detail": detail}
    with _LOCK:
        _JOB["steps"].append(step)
    return step


def _update_step(step: Dict[str, Any], *, status: Optional[str] = None, detail: Optional[str] = None) -> None:
    with _LOCK:
        if status is not None:
            step["status"] = status
        if detail is not None:
            step["detail"] = detail


def _set_phase(phase: Optional[str]) -> None:
    with _LOCK:
        _JOB["phase"] = phase


def get_cost_demo_status() -> Dict[str, Any]:
    """Snapshot of the current/last job (safe to poll)."""
    import copy

    with _LOCK:
        return copy.deepcopy(_JOB)


# --------------------------------------------------------------------------- #
# Galileo REST helpers
# --------------------------------------------------------------------------- #
def _client():
    import httpx

    api = (os.environ.get("GALILEO_API_URL") or "").rstrip("/")
    key = os.environ.get("GALILEO_API_KEY") or ""
    if not api or not key:
        raise RuntimeError("GALILEO_API_URL / GALILEO_API_KEY not set")
    return httpx.Client(base_url=api, headers={"Galileo-API-Key": key}, timeout=60.0)


def _set_price(client, model: str, price: float) -> None:
    r = client.put(
        f"/models/{model}/price_overrides",
        json={"input_price": float(price), "output_price": float(price)},
    )
    r.raise_for_status()


def _clear_price(client, model: str) -> int:
    r = client.delete(f"/models/{model}/price_overrides")
    # 204 on success, 404 if there was no override — both are fine.
    return r.status_code


def _cost_daily(client, project_id: str, start_iso: str, end_iso: str) -> List[Dict[str, Any]]:
    """Per-day cost points for a project, summed across all cost features.

    Retries a few times because the summary endpoint has occasionally returned
    a non-JSON body mid-pagination.
    """
    params = {"start_time": start_iso, "end_time": end_iso, "interval": "daily"}
    last_err: Optional[str] = None
    for _ in range(4):
        try:
            r = client.get("/integrations/costs/summary", params=params)
            r.raise_for_status()
            data = r.json()
            by_day: Dict[str, float] = {}
            for feat in data.get("features", []):
                for pr in feat.get("projects", []):
                    if pr.get("project_id") == project_id:
                        for dp in pr.get("data_points", []):
                            ts = dp.get("timestamp", "")
                            by_day[ts] = by_day.get(ts, 0.0) + float(dp.get("cost", 0) or 0)
            return [{"timestamp": ts, "cost": c} for ts, c in sorted(by_day.items())]
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(1.5)
    raise RuntimeError(f"cost summary failed: {last_err}")


def _delete_traces(client, project_id: str, log_stream_id: str, start_iso: str, end_iso: str) -> str:
    """Delete traces in [start, end] for a log stream. Returns the API message."""
    filters = [
        {"column_id": "created_at", "operator": "gte", "value": start_iso, "type": "date"},
        {"column_id": "created_at", "operator": "lte", "value": end_iso, "type": "date"},
    ]
    r = client.post(
        f"/projects/{project_id}/traces/delete",
        json={"log_stream_id": log_stream_id, "filters": filters},
    )
    r.raise_for_status()
    try:
        return r.json().get("message", "deleted")
    except Exception:  # noqa: BLE001
        return "deleted"


def _detect_problem_window(client, project_id: str, tz: ZoneInfo, lookback_days: int = 21):
    """Find the earliest 'broken' day (cost $0 or a missing bucket, or well below
    the median of healthy days) in the recent window. Returns a tz-aware start
    datetime at that day's 00:00, or None if the curve looks healthy."""
    import statistics

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)
    dps = _cost_daily(client, project_id, start.strftime(_ISO), end.strftime(_ISO))
    present = {dp["timestamp"][:10]: float(dp.get("cost", 0) or 0) for dp in dps}
    nonzero = [c for c in present.values() if c > 0]
    if not nonzero:
        return None
    med = statistics.median(nonzero)

    # Days that scored abnormally low (partial failure) or exactly $0.
    problems = [d for d, c in present.items() if c == 0 or c < 0.2 * med]

    # Missing buckets after the first day we have data for (a fully-failed day
    # like Sep 3 shows up as no data point at all).
    first_present = min(present) if present else None
    day = start.date()
    while day <= end.date():
        ds = day.isoformat()
        if ds not in present and first_present and ds > first_present and ds < end.date().isoformat():
            problems.append(ds)
        day += timedelta(days=1)

    if not problems:
        return None
    earliest = min(problems)
    return datetime.combine(date.fromisoformat(earliest), dtime(0, 0), tzinfo=tz)


def _last_nonzero_day(client, project_id: str) -> Optional[str]:
    """Latest YYYY-MM-DD (UTC bucket) where this project's cost was > 0."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=120)
    dps = _cost_daily(client, project_id, start.strftime(_ISO), end.strftime(_ISO))
    days = [dp["timestamp"][:10] for dp in dps if float(dp.get("cost", 0) or 0) > 0]
    return max(days) if days else None


def _window_cost(client, project_id: str, start_iso: str, end_iso: str) -> float:
    return sum(float(dp.get("cost", 0) or 0) for dp in _cost_daily(client, project_id, start_iso, end_iso))


# --------------------------------------------------------------------------- #
# Project / metric provisioning (self-heal)
# --------------------------------------------------------------------------- #
def _enable_scorers(log_stream, scorer_ids: List[str]) -> Dict[str, Any]:
    """Enable exactly ``scorer_ids`` on the stream (idempotent for these
    dedicated projects, whose enabled set IS these scorers)."""
    try:
        log_stream.enable_metrics(list(scorer_ids))
        return {"status": "ok"}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}


def _build_specs(
    llm_project: Optional[str],
    luna_project: Optional[str],
    llm_price: Optional[float],
    luna_price: Optional[float],
) -> List[Dict[str, Any]]:
    """Copy the captured specs, overriding project name / price for test runs.

    Test runs pass throwaway project names but reuse the SAME org-level scorer
    ids, so the test projects get the identical metric set.
    """
    overrides = [(llm_project, llm_price), (luna_project, luna_price)]
    specs: List[Dict[str, Any]] = []
    for base, (name, price) in zip(PROJECT_SPECS, overrides):
        s = dict(base)
        s["scorers"] = list(base["scorers"])
        if name and name.strip():
            s["name"] = name.strip()
        if price is not None:
            s["price"] = float(price)
        specs.append(s)
    return specs


def _ensure_project_ready(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Create the project + Default stream if missing and (re)enable metrics.
    Returns {name, project_id, log_stream_id, created(bool), metrics_status}."""
    name = spec["name"]
    proj = _ensure_project(name)
    project_id = proj.get("id")
    if proj.get("status") == "error" or not project_id:
        return {"name": name, "error": proj.get("error", "project resolve failed")}

    log_stream, ls_status = _ensure_log_stream(name, LOG_STREAM_NAME, project_id=project_id)
    log_stream_id = ls_status.get("id")
    if log_stream is None or not log_stream_id:
        return {"name": name, "project_id": project_id, "error": ls_status.get("error", "log stream failed")}

    created = proj.get("status") == "created" or ls_status.get("status") == "created"
    # Always (re)enable so a freshly recreated project gets its metrics back.
    metrics = _enable_scorers(log_stream, [sid for sid, _ in spec["scorers"]])
    return {
        "name": name,
        "project_id": str(project_id),
        "log_stream_id": str(log_stream_id),
        "created": created,
        "metrics_status": metrics.get("status"),
        "metrics_error": metrics.get("error"),
    }


# --------------------------------------------------------------------------- #
# Injector (loaded by path — it lives in a hyphenated folder)
# --------------------------------------------------------------------------- #
def _load_injector() -> Callable[..., Any]:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # ai-ops-desk/
    path = os.path.join(here, "integration-cost-demo", "inject_cost_traces.py")
    spec = importlib.util.spec_from_file_location("inject_cost_traces", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load injector at {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.inject_cost_traces


# --------------------------------------------------------------------------- #
# Window planning
# --------------------------------------------------------------------------- #
def _parse_local(value: str, tz: ZoneInfo) -> datetime:
    raw = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        dt = datetime.combine(date.fromisoformat(raw), dtime(0, 0))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def _plan_window(
    client,
    project_ids: List[str],
    tz_name: str,
    start_override: Optional[str],
    end_override: Optional[str],
) -> Tuple[datetime, datetime, int]:
    """Shared window for BOTH projects so their timestamps overlay exactly.

    Default start = the day AFTER the latest non-$0 day across the two projects
    (i.e. "take it up from where cost went to $0"). Default end = now.
    """
    tz = ZoneInfo(tz_name)
    end_dt = _parse_local(end_override, tz) if end_override else datetime.now(tz)

    if start_override:
        start_dt = _parse_local(start_override, tz)
    else:
        last_days = [d for d in (_last_nonzero_day(client, pid) for pid in project_ids) if d]
        if last_days:
            anchor = date.fromisoformat(max(last_days)) + timedelta(days=1)
            start_dt = datetime.combine(anchor, dtime(0, 0), tzinfo=tz)
        else:
            start_dt = end_dt - timedelta(days=FALLBACK_BACKFILL_DAYS)

    if end_dt <= start_dt:
        return start_dt, end_dt, 0

    window_days = (end_dt - start_dt).total_seconds() / 86400.0
    traces = int(round(TRACES_PER_DAY * window_days))
    traces = max(int(TRACES_PER_DAY), min(traces, MAX_TRACES))
    return start_dt, end_dt, traces


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _run_cost_demo(
    *,
    specs: List[Dict[str, Any]],
    start: Optional[str],
    end: Optional[str],
    tz_name: str,
    seed: int,
) -> None:
    inject = _load_injector()
    with _client() as client:
        # 1) Ensure both projects/streams/metrics.
        prep = _add_step("Ensure projects & metrics", "running")
        ready: List[Dict[str, Any]] = []
        for spec in specs:
            info = _ensure_project_ready(spec)
            if info.get("error"):
                _update_step(prep, status="error", detail=f"{info['name']}: {info['error']}")
                raise RuntimeError(f"{info['name']}: {info['error']}")
            ready.append(info)
        detail = ", ".join(
            f"{r['name']}{' (recreated)' if r.get('created') else ''} "
            f"[metrics {r.get('metrics_status')}]"
            for r in ready
        )
        _update_step(prep, status="ok", detail=detail)

        # 2) Plan the shared window.
        planning = _add_step("Plan shared window", "running")
        start_dt, end_dt, traces = _plan_window(
            client, [r["project_id"] for r in ready], tz_name, start, end
        )
        start_z = start_dt.astimezone(timezone.utc).strftime(_ISO)
        end_z = end_dt.astimezone(timezone.utc).strftime(_ISO)
        days = round((end_dt - start_dt).total_seconds() / 86400.0, 2)
        with _LOCK:
            _JOB["window"] = {"start": start_z, "end": end_z, "days": days, "traces": traces}
        if traces <= 0:
            _update_step(planning, status="ok", detail="already up to date — nothing to inject")
            with _LOCK:
                _JOB["summary"] = {"note": "Cost graph already current; no traces injected."}
            return
        _update_step(planning, status="ok", detail=f"{traces} traces over {days}d ({start_z} → {end_z})")

        summary: Dict[str, Any] = {}
        try:
            # 3) Phased inject: each project at its own frozen price.
            for spec, info in zip(specs, ready):
                name = spec["name"]
                price = spec["price"]
                _set_phase(name)

                price_step = _add_step(f"{name}: set {EVAL_MODEL} → ${price:,.0f}/1M", "running")
                _set_price(client, EVAL_MODEL, price)
                _update_step(price_step, status="ok")

                inject_step = _add_step(f"{name}: inject {traces} traces", "running")
                inject(
                    name,
                    LOG_STREAM_NAME,
                    traces=traces,
                    start=start_z,
                    end=end_z,
                    tz_name=tz_name,
                    seed=seed,
                    num_metrics=len(spec["scorers"]),
                    dry_run=False,
                )
                _update_step(inject_step, status="ok")

                # 4) Poll scoring until the window cost plateaus (freezes at price).
                score_step = _add_step(f"{name}: wait for scoring @ ${price:,.0f}", "running")
                total = _poll_scoring(client, info["project_id"], start_z, end_z, score_step)
                _update_step(score_step, status="ok", detail=f"window cost ≈ ${total:,.0f}")
                summary[name] = {"window_cost": round(total, 2), "price": price, "traces": traces}
        finally:
            # 5) Always revert the org-wide price so live traffic isn't inflated.
            _set_phase(None)
            reset_step = _add_step(f"Reset {EVAL_MODEL} price override", "running")
            try:
                code = _clear_price(client, EVAL_MODEL)
                _update_step(reset_step, status="ok", detail=f"override removed (HTTP {code})")
                summary["price_reset"] = True
            except Exception as e:  # noqa: BLE001
                _update_step(reset_step, status="error", detail=f"{type(e).__name__}: {e}")
                summary["price_reset"] = False

        with _LOCK:
            _JOB["summary"] = summary


def _poll_scoring(client, project_id: str, start_iso: str, end_iso: str, step: Dict[str, Any]) -> float:
    """Poll the window cost until two consecutive reads agree (and are > 0), or
    the timeout hits. Returns the last observed total."""
    prev: Optional[float] = None
    deadline = time.time() + SCORING_TIMEOUT_SECONDS
    last = 0.0
    while time.time() < deadline:
        try:
            last = _window_cost(client, project_id, start_iso, end_iso)
        except Exception as e:  # noqa: BLE001
            _update_step(step, detail=f"poll error: {e}")
            time.sleep(POLL_SECONDS)
            continue
        _update_step(step, detail=f"scoring… window cost ≈ ${last:,.0f}")
        if prev is not None and last > 1.0 and abs(last - prev) <= max(1.0, 0.01 * last):
            return last
        prev = last
        time.sleep(POLL_SECONDS)
    return last


# --------------------------------------------------------------------------- #
# Public entrypoints
# --------------------------------------------------------------------------- #
def start_cost_demo(
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    tz_name: str = DEFAULT_TZ,
    seed: int = SEED,
    llm_project: Optional[str] = None,
    luna_project: Optional[str] = None,
    llm_price: Optional[float] = None,
    luna_price: Optional[float] = None,
) -> Dict[str, Any]:
    """Kick off the phased job in a background thread (one at a time).

    Leave ``llm_project`` / ``luna_project`` blank to target the real
    ``LLM_Evals`` / ``Luna_Evals`` projects. Pass throwaway names to test the
    flow against disposable projects (same metrics, deletable afterwards via
    ``delete_cost_demo_projects``).
    """
    specs = _build_specs(llm_project, luna_project, llm_price, luna_price)
    with _LOCK:
        if _JOB.get("state") == "running":
            return {"started": False, "reason": "a cost-demo run is already in progress"}
        _reset_job()
        _JOB["kind"] = "extend"
        _JOB["targets"] = [s["name"] for s in specs]
        _JOB["is_test"] = any(s["name"] not in PROTECTED_PROJECTS for s in specs)

    def _worker() -> None:
        try:
            _run_cost_demo(specs=specs, start=start, end=end, tz_name=tz_name, seed=seed)
            with _LOCK:
                _JOB["state"] = "done"
        except Exception as e:  # noqa: BLE001
            with _LOCK:
                _JOB["state"] = "error"
                _JOB["error"] = f"{type(e).__name__}: {e}"
        finally:
            with _LOCK:
                _JOB["finished_at"] = _now_iso()

    threading.Thread(target=_worker, name="cost-demo", daemon=True).start()
    return {"started": True, "targets": [s["name"] for s in specs]}


def _heal_one(client, inject, spec: Dict[str, Any], info: Dict[str, Any], start_dt, end_dt, tz_name: str, seed: int) -> Dict[str, Any]:
    """Set the price, delete + re-inject one project's broken window, poll."""
    name = spec["name"]
    price = float(spec["price"])
    window_days = (end_dt - start_dt).total_seconds() / 86400.0
    traces = max(int(TRACES_PER_DAY), min(int(round(TRACES_PER_DAY * window_days)), MAX_TRACES))
    start_z = start_dt.astimezone(timezone.utc).strftime(_ISO)
    end_z = end_dt.astimezone(timezone.utc).strftime(_ISO)

    price_step = _add_step(f"{name}: set {EVAL_MODEL} → ${price:,.0f}/1M", "running")
    _set_price(client, EVAL_MODEL, price)
    _update_step(price_step, status="ok")

    del_step = _add_step(f"{name}: delete traces in window", "running")
    msg = _delete_traces(client, info["project_id"], info["log_stream_id"], start_z, end_z)
    _update_step(del_step, status="ok", detail=msg)

    inj_step = _add_step(f"{name}: re-inject {traces} traces ({start_z[:10]}→now)", "running")
    inject(
        name,
        LOG_STREAM_NAME,
        traces=traces,
        start=start_z,
        end=end_z,
        tz_name=tz_name,
        seed=seed,
        num_metrics=len(spec["scorers"]),
        dry_run=False,
    )
    _update_step(inj_step, status="ok")

    score_step = _add_step(f"{name}: wait for scoring @ ${price:,.0f}", "running")
    total = _poll_scoring(client, info["project_id"], start_z, end_z, score_step)
    _update_step(score_step, status="ok", detail=f"window cost ≈ ${total:,.0f}")
    return {"window_cost": round(total, 2), "price": price, "traces": traces, "from": start_z[:10]}


def _run_fix(
    *,
    specs: List[Dict[str, Any]],
    start: Optional[str],
    end: Optional[str],
    tz_name: str,
    seed: int,
) -> None:
    """Scan each project for scoring gaps and heal whichever dipped, each at its
    own frozen price (sequenced, since pricing is org-wide per model). Projects
    that look healthy are skipped."""
    inject = _load_injector()
    tz = ZoneInfo(tz_name)
    with _client() as client:
        prep = _add_step("Ensure projects & metrics", "running")
        readys: List[Dict[str, Any]] = []
        for spec in specs:
            info = _ensure_project_ready(spec)
            if info.get("error"):
                _update_step(prep, status="error", detail=f"{spec['name']}: {info['error']}")
                raise RuntimeError(f"{spec['name']}: {info['error']}")
            readys.append(info)
        _update_step(prep, status="ok", detail=", ".join(r["name"] for r in readys))

        # Scan for gaps (or use the explicit window for ALL projects if given).
        scan = _add_step("Scan for scoring gaps", "running")
        end_dt = _parse_local(end, tz) if end else datetime.now(tz)
        to_heal: List[Tuple[Dict[str, Any], Dict[str, Any], Any]] = []
        scan_notes: List[str] = []
        for spec, info in zip(specs, readys):
            if start:
                start_dt = _parse_local(start, tz)
            else:
                start_dt = _detect_problem_window(client, info["project_id"], tz)
            if start_dt is None or end_dt <= start_dt:
                scan_notes.append(f"{spec['name']}: healthy")
                continue
            scan_notes.append(f"{spec['name']}: gap from {start_dt.date()}")
            to_heal.append((spec, info, start_dt))
        _update_step(scan, status="ok", detail=" · ".join(scan_notes))

        if not to_heal:
            with _LOCK:
                _JOB["summary"] = {"note": "Both curves look healthy; nothing to fix."}
            return

        summary: Dict[str, Any] = {}
        try:
            for spec, info, start_dt in to_heal:
                _set_phase(spec["name"])
                summary[spec["name"]] = _heal_one(client, inject, spec, info, start_dt, end_dt, tz_name, seed)
        finally:
            _set_phase(None)
            reset_step = _add_step(f"Reset {EVAL_MODEL} price override", "running")
            try:
                code = _clear_price(client, EVAL_MODEL)
                _update_step(reset_step, status="ok", detail=f"override removed (HTTP {code})")
            except Exception as e:  # noqa: BLE001
                _update_step(reset_step, status="error", detail=f"{type(e).__name__}: {e}")
        with _LOCK:
            _JOB["summary"] = summary


def start_cost_fix(
    *,
    llm_project: Optional[str] = None,
    luna_project: Optional[str] = None,
    llm_price: Optional[float] = None,
    luna_price: Optional[float] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    tz_name: str = DEFAULT_TZ,
    seed: int = SEED,
) -> Dict[str, Any]:
    """Kick off a scoring-gap heal in the background. Scans BOTH projects and
    heals whichever dipped (LLM_Evals @ $1,830 and/or Luna_Evals @ $80). Pass
    throwaway names to heal test-mode sandbox projects instead."""
    specs = _build_specs(llm_project, luna_project, llm_price, luna_price)
    with _LOCK:
        if _JOB.get("state") == "running":
            return {"started": False, "reason": "a cost-demo run is already in progress"}
        _reset_job()
        _JOB["kind"] = "fix"
        _JOB["targets"] = [s["name"] for s in specs]

    def _worker() -> None:
        try:
            _run_fix(specs=specs, start=start, end=end, tz_name=tz_name, seed=seed)
            with _LOCK:
                _JOB["state"] = "done"
        except Exception as e:  # noqa: BLE001
            with _LOCK:
                _JOB["state"] = "error"
                _JOB["error"] = f"{type(e).__name__}: {e}"
        finally:
            with _LOCK:
                _JOB["finished_at"] = _now_iso()

    threading.Thread(target=_worker, name="cost-demo-fix", daemon=True).start()
    return {"started": True, "targets": [s["name"] for s in specs]}


def delete_cost_demo_projects(names: List[str]) -> Dict[str, Any]:
    """Delete throwaway test projects by name. Refuses the protected real
    projects (``LLM_Evals`` / ``Luna_Evals``) so a test cleanup can never wipe
    the live demo data."""
    from galileo.projects import Projects

    results: Dict[str, Any] = {}
    projects = Projects()
    with _client() as client:
        for raw in names:
            name = (raw or "").strip()
            if not name:
                continue
            if name in PROTECTED_PROJECTS:
                results[name] = {"status": "protected"}
                continue
            try:
                proj = projects.get(name=name)
                if proj is None:
                    results[name] = {"status": "not_found"}
                    continue
                r = client.delete(f"/projects/{proj.id}")
                if r.status_code in (200, 204):
                    results[name] = {"status": "deleted"}
                else:
                    results[name] = {
                        "status": "error",
                        "http": r.status_code,
                        "detail": r.text[:200],
                    }
            except Exception as e:  # noqa: BLE001
                results[name] = {"status": "error", "error": f"{type(e).__name__}: {e}"}
    return {"results": results}
