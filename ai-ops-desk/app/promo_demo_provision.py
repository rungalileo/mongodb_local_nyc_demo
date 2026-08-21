"""One-click provisioning for the expired-promo spike demo.

Powers the Ops-view "Create demo project" button. Given a project + log stream
name, it does everything needed to show the leak end-to-end in a *fresh* Galileo
project/org:

  1. Create the project (idempotent).
  2. Create the log stream (idempotent).
  3. Create + enable the trace-level LLM-as-judge metric that flags traces where
     an EXPIRED promo was applied.
  4. Create + bind the Agent Control "steer" control that catches an expired
     promo at proposal time (``check_promotions``) and steers the agent back to
     live offers.
  5. Inject the spike-shaped synthetic traffic (normal live baseline -> expired
     clearance spike) so "Generate signal" has data to detect immediately.

Every step is best-effort and reported back independently: a failure in one
(e.g. the org's key can't create Agent Control controls) does not abort the
others, and the response tells the caller exactly what happened so the missing
piece can be finished by hand.

Note on the steer control: it is a *runtime* guardrail. Binding it to the new
log stream only changes behavior for a live agent pointed at that stream; it
does not retroactively alter the historical traces injected here. When
``set_active`` is on (default), this module repoints the running app at the new
project/log stream so subsequent live chat traces land there and the steer
control guards them too.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

# Hard cap on injected traces. Each session is a real trace written to Galileo,
# so this bounds how long the button's request runs and how much it writes.
MAX_SESSIONS = int(os.getenv("PROMO_DEMO_MAX_SESSIONS", "500"))

# ---- LLM-as-judge metric --------------------------------------------------

PROMO_METRIC_NAME = os.getenv("PROMO_METRIC_NAME", "Expired Promo Applied")

PROMO_METRIC_PROMPT = (
    "You are auditing a single AI shopping-assistant conversation (one full "
    "trace). The assistant can look up promotions for a product, PROPOSE a "
    "discount to the customer, and APPLY that discount to the cart.\n\n"
    "A promotion is EXPIRED when its end date (fields like `promo_end_date` / "
    "`effective_until`) is in the PAST. The trace metadata and the "
    "\"Check Promotions\" / \"Select Promotion\" / \"Apply Discount\" steps expose "
    "`promo_expired` / `chosen_promo_expired` flags, a `promo_stage` (e.g. "
    "\"proposed\"), and the `discount_usd`.\n\n"
    "Return TRUE if, ANYWHERE in this trace, the assistant SURFACED an EXPIRED / "
    "outdated promotion to the customer — this includes BOTH:\n"
    "  (a) merely PROPOSING or offering it (e.g. a \"Check Promotions\" step or "
    "a reply that pitches a promo whose end date has already passed; "
    "`promo_expired` true and/or `promo_stage` = \"proposed\"), AND\n"
    "  (b) APPLYING / adding it to the cart (an \"Apply Discount\" step whose "
    "`promo_expired` is true, or a reply confirming such a discount).\n"
    "Proposing an expired promo is enough to return TRUE even if it was never "
    "applied.\n\n"
    "Return FALSE only if the assistant NEVER surfaced an expired promotion — "
    "i.e. it proposed and/or applied only currently-valid (non-expired) "
    "promotions, found no promotion at all, or an expired promo was correctly "
    "blocked / steered away / declined so the customer only ever saw a live "
    "offer or full price.\n\n"
    "Judge only from the trace content."
)

# Customer-sentiment judge. This one is NOT created by the button — it is
# assumed to already exist in the org (built by hand as a multi-label
# positive/neutral/negative metric); the button only *enables* it by name.
CUSTOMER_SENTIMENT_METRIC_NAME = os.getenv("SENTIMENT_METRIC_NAME", "customer-sentiment")

# Galileo built-in (preset) scorers to enable alongside the custom judges. These
# exist org-wide, so they resolve by name; they also drive LLM-evaluator cost.
PRESET_METRIC_NAMES: List[str] = [
    "instruction_adherence",
    "reasoning_coherence",
    "output_tone",
    "context_adherence",
    "completeness",
    "tool_error_rate",
]

# ---- Agent Control steer control -----------------------------------------
# The control itself (name below) is built by hand in the Console — see the
# "Agent Control steer control" table in EXPIRED_PROMO_DEMO.md for its exact
# scope / JSON evaluator / steering message. The button only *binds* it.

STEER_CONTROL_NAME = os.getenv("PROMO_STEER_CONTROL_NAME", "promo-proposal-steer")


# ---- Steps ----------------------------------------------------------------


def _ensure_project(project_name: str) -> Dict[str, Any]:
    from galileo.projects import Projects, create_project

    existing = None
    try:
        existing = Projects().get(name=project_name)
    except Exception:
        existing = None
    if existing is not None:
        return {"status": "exists", "id": getattr(existing, "id", None), "name": project_name}

    try:
        project = create_project(name=project_name)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "name": project_name, "error": f"{type(e).__name__}: {e}"}
    return {"status": "created", "id": getattr(project, "id", None), "name": project_name}


def _ensure_log_stream(project_name: str, log_stream_name: str, project_id: Optional[str] = None):
    """Return (log_stream_obj_or_None, status_dict). Idempotent.

    Prefers ``project_id`` for lookup/creation so we never depend on the SDK
    resolving the project by name (which 404s "Project not found" when the name
    doesn't cleanly round-trip — spaces, casing, or a just-created project).
    Creation failures are returned as ``status="error"`` rather than raised, so
    the caller can report a clean partial result.
    """
    from galileo.log_streams import LogStreams, create_log_stream

    get_kwargs: Dict[str, Any] = {"name": log_stream_name}
    if project_id:
        get_kwargs["project_id"] = project_id
    else:
        get_kwargs["project_name"] = project_name

    existing = None
    try:
        existing = LogStreams().get(**get_kwargs)
    except Exception:
        existing = None
    if existing is not None:
        return existing, {
            "status": "exists",
            "id": getattr(existing, "id", None),
            "project_id": getattr(existing, "project_id", None),
            "name": log_stream_name,
        }

    try:
        if project_id:
            ls = create_log_stream(name=log_stream_name, project_id=project_id)
        else:
            ls = create_log_stream(name=log_stream_name, project_name=project_name)
    except Exception as e:  # noqa: BLE001
        return None, {
            "status": "error",
            "name": log_stream_name,
            "project_id": project_id,
            "error": f"{type(e).__name__}: {e}",
        }
    return ls, {
        "status": "created",
        "id": getattr(ls, "id", None),
        "project_id": getattr(ls, "project_id", None),
        "name": log_stream_name,
    }


def _enable_metrics_resilient(log_stream, names: List[str]) -> Dict[str, Any]:
    """Enable ``names`` on the stream, tolerating names that don't resolve.

    ``enable_metrics`` REPLACES the enabled set and raises ValueError listing any
    unknown names before registering anything, so one bad name would enable
    nothing. We catch that, drop the unknown names it reports, and retry — so the
    metrics that DO exist get enabled even if one custom judge (e.g.
    ``expired-promo-applied`` or ``customer-sentiment``) hasn't been created in
    the org yet; the missing ones come back in ``skipped``.
    """
    remaining = list(names)
    skipped: List[str] = []
    last_error: Optional[str] = None
    for _ in range(len(names) + 1):
        if not remaining:
            break
        try:
            log_stream.enable_metrics(remaining)
            return {"enabled": list(remaining), "skipped": skipped}
        except ValueError as e:  # "non-existent metrics are specified: 'x', 'y'"
            last_error = str(e)
            unknown = [u for u in re.findall(r"'([^']+)'", last_error) if u in remaining]
            if not unknown:
                break
            skipped.extend(unknown)
            remaining = [n for n in remaining if n not in unknown]
        except Exception as e:  # network/other — report and stop
            last_error = f"{type(e).__name__}: {e}"
            break
    return {"enabled": list(remaining), "skipped": skipped, "error": last_error}


def _resolve_metric_identifiers(names: List[str]) -> Dict[str, str]:
    """Map each requested metric name to the scorer's actual **id** when a
    normalized (trimmed + case-insensitive) match exists in the org.

    This defends against Console data-entry quirks — e.g. a custom judge saved
    as ``'Expired Promo Applied '`` with a trailing space, which an exact label
    match silently misses. Enabling by id sidesteps name/label/casing entirely.
    Names with no match are omitted (the caller passes them through unchanged so
    presets still resolve by slug and truly-missing ones get reported).
    """
    from galileo.scorers import Scorers

    try:
        rows = Scorers().list()
    except Exception:
        return {}
    norm: Dict[str, Any] = {}
    for r in rows:
        for key in (getattr(r, "name", None), getattr(r, "label", None)):
            if key and getattr(r, "id", None):
                norm.setdefault(key.strip().casefold(), r)
    resolved: Dict[str, str] = {}
    for n in names:
        m = norm.get(n.strip().casefold())
        if m is not None:
            resolved[n] = str(m.id)
    return resolved


def _ensure_metric(log_stream) -> Dict[str, Any]:
    """Enable the demo metric set on the stream BEFORE injection, so metrics
    score arriving traces. This ONLY enables — nothing is created; all of these
    are expected to already exist in the org/console:

      - ``Expired Promo Applied``   (custom; built by hand)
      - ``customer-sentiment``      (custom; built by hand)
      - 6 Galileo presets           (instruction/reasoning/tone/context/completeness/tool-error)

    Custom names are resolved to their scorer **id** first (trim/case-insensitive)
    so trailing spaces or casing in the Console don't break the match; anything
    that still doesn't resolve is skipped and reported in ``skipped_metrics``
    rather than failing the whole set.
    """
    names = [PROMO_METRIC_NAME, CUSTOMER_SENTIMENT_METRIC_NAME, *PRESET_METRIC_NAMES]
    id_by_name = _resolve_metric_identifiers(names)
    # Enable by id where we resolved one; otherwise pass the name through.
    identifiers = [id_by_name.get(n, n) for n in names]
    name_by_id = {v: k for k, v in id_by_name.items()}

    result: Dict[str, Any] = {"name": PROMO_METRIC_NAME}
    outcome = _enable_metrics_resilient(log_stream, identifiers)
    # Translate ids back to human names for readable reporting.
    result["enabled_metrics"] = [name_by_id.get(x, x) for x in outcome.get("enabled", [])]
    result["skipped_metrics"] = [name_by_id.get(x, x) for x in outcome.get("skipped", [])]
    if outcome.get("error"):
        result["enable_error"] = outcome["error"]
    result["enabled"] = bool(result["enabled_metrics"])
    result["status"] = "ok" if result["enabled"] else "enable_failed"
    return result


def _ensure_steer_control(log_stream_id: Optional[str]) -> Dict[str, Any]:
    """Attach the EXISTING ``promo-proposal-steer`` control to the log stream,
    DISABLED — it shows up *attached but inactive* so the operator flips it on
    live. This does NOT create the control: it is expected to already exist in
    the org (built by hand). We look it up by name and bind it; if it isn't
    found we report ``not_found`` rather than creating it. Uses the ACE REST API
    with the Galileo-API-Key header, mirroring
    ``agent_control_setup._manual_log_stream_binding_status``.
    """
    server_url = os.environ.get("AGENT_CONTROL_URL")
    api_key = os.environ.get("AGENT_CONTROL_API_KEY") or os.environ.get("GALILEO_API_KEY")
    api_key_header = os.environ.get("AGENT_CONTROL_API_KEY_HEADER", "Galileo-API-Key")

    result: Dict[str, Any] = {"name": STEER_CONTROL_NAME, "created": False}
    if not server_url or not api_key:
        result["status"] = "skipped"
        result["reason"] = "AGENT_CONTROL_URL or API key not set"
        return result
    if not log_stream_id:
        result["status"] = "skipped"
        result["reason"] = "log stream id unresolved"
        return result

    try:
        import httpx

        headers = {api_key_header: api_key}
        control_id: Optional[Any] = None
        with httpx.Client(base_url=server_url.rstrip("/"), timeout=30.0) as client:
            # Resolve the pre-existing control by name (do NOT create it). NOTE:
            # the list endpoint rejects limit>100 with 422, so keep this at 100.
            listing = client.get("/api/v1/controls", params={"limit": 100}, headers=headers)
            listing.raise_for_status()
            items = listing.json()
            items = items.get("controls", items) if isinstance(items, dict) else items
            for c in items or []:
                if isinstance(c, dict) and c.get("name") == STEER_CONTROL_NAME:
                    control_id = c.get("id") or c.get("control_id")
                    break

            if control_id is None:
                result["status"] = "not_found"
                result["error"] = (
                    f"control {STEER_CONTROL_NAME!r} does not exist in this org — "
                    "create it in the Console first (it is not auto-created)."
                )
                return result
            result["control_id"] = control_id

            # Bind DISABLED: attached to the stream but not active until the
            # operator toggles it on during the demo.
            bind_resp = client.put(
                "/api/v1/control-bindings/by-key",
                json={
                    "target_type": "log_stream",
                    "target_id": log_stream_id,
                    "control_id": control_id,
                    "enabled": False,
                },
                headers=headers,
            )
            bind_resp.raise_for_status()
            result["bound"] = True
            result["binding_enabled"] = False
            result["status"] = "ok"

            # Verify the binding actually exists on the injected stream so a
            # silent API hiccup can't leave us thinking the steer is active.
            try:
                verify = client.get(
                    "/api/v1/control-bindings",
                    params={"target_type": "log_stream", "target_id": log_stream_id, "limit": 100},
                    headers=headers,
                )
                verify.raise_for_status()
                bound_ids = {
                    b.get("control_id") for b in (verify.json().get("bindings") or [])
                }
                result["verified"] = control_id in bound_ids
                result["target_id"] = log_stream_id
            except Exception as e:  # noqa: BLE001
                result["verified"] = None
                result["verify_error"] = f"{type(e).__name__}: {e}"
    except Exception as e:
        result["status"] = "error"
        result["error"] = f"{type(e).__name__}: {e}"
    return result


# Persisted "active target" so a provisioned project survives process restarts
# (uvicorn --reload on every code save, or a container restart). Without this,
# api.py's ``load_dotenv(override=True)`` snaps GALILEO_PROJECT back to the .env
# default on the next boot and live chat drifts back to the old stream.
_ACTIVE_TARGET_FILE = os.environ.get(
    "PROMO_DEMO_STATE_FILE",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".galileo_active_target.json"),
)


def _persist_active_target(
    project_name: str,
    log_stream_name: str,
    project_id: Optional[str],
    log_stream_id: Optional[str],
) -> Optional[str]:
    """Write the current live target to disk so ``restore_active_target`` can
    re-apply it after a restart. Best-effort; returns an error string or None.
    """
    import json

    try:
        with open(_ACTIVE_TARGET_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "project": project_name,
                    "log_stream": log_stream_name,
                    "project_id": project_id,
                    "log_stream_id": log_stream_id,
                },
                f,
            )
        return None
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"


def _target_exists(project_id: Optional[str], log_stream_id: Optional[str]) -> str:
    """Check whether a pinned target still exists in Galileo.

    Returns ``"ok"`` (both present), ``"missing"`` (project or stream was
    definitively deleted — ``.get`` returned None), or ``"unknown"`` (couldn't
    verify: no creds / network error / no ids to check). We only self-heal on
    ``"missing"`` so a transient blip never wipes a valid target.
    """
    if not project_id or not log_stream_id:
        return "unknown"  # nothing pinned to verify by id
    if not (os.environ.get("GALILEO_API_KEY") and os.environ.get("GALILEO_API_URL")):
        return "unknown"  # SDK not configured to check
    try:
        from galileo.projects import Projects
        from galileo.log_streams import LogStreams

        try:
            from galileo.exceptions import NotFoundError
        except Exception:  # pragma: no cover - defensive import
            NotFoundError = ()  # type: ignore[assignment]

        try:
            if Projects().get(id=str(project_id)) is None:
                return "missing"
            if LogStreams().get(id=str(log_stream_id), project_id=str(project_id)) is None:
                return "missing"
            return "ok"
        except NotFoundError:
            # A deleted project/stream 404s here — that's the case we heal.
            return "missing"
    except Exception:
        # No creds, network blip, or a non-404 error (e.g. malformed id):
        # don't wipe a target we couldn't actually disprove.
        return "unknown"


def restore_active_target() -> Optional[Dict[str, Any]]:
    """Re-apply a previously provisioned live target on process startup.

    Call this AFTER ``load_dotenv`` so it takes precedence over the .env
    defaults. Sets the same env vars ``apply_live_target`` does, so the first
    trace and Agent Control init both bind to the last-provisioned stream. Safe
    no-op when no state file exists. Returns the restored target or None.

    Self-heal: if the pinned project/log stream was deleted, the state file is
    cleared and we fall back to the .env default instead of pinning a dead
    target (which would 404 every trace silently). A transient/uncheckable
    result keeps the target as-is.
    """
    import json

    try:
        with open(_ACTIVE_TARGET_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except Exception:
        return None

    project = (data.get("project") or "").strip()
    log_stream = (data.get("log_stream") or "").strip()
    if not project or not log_stream:
        return None

    project_id = data.get("project_id")
    log_stream_id = data.get("log_stream_id")

    # Don't pin a target that no longer exists — revert to the .env default.
    if _target_exists(project_id, log_stream_id) == "missing":
        clear_active_target()
        print(
            f"[startup] persisted live target {project!r}/{log_stream!r} no longer "
            "exists — cleared it; falling back to the .env default."
        )
        return None

    os.environ["GALILEO_PROJECT"] = project
    os.environ["GALILEO_LOG_STREAM"] = log_stream
    if project_id and log_stream_id:
        os.environ["GALILEO_PROJECT_ID"] = str(project_id)
        os.environ["GALILEO_LOG_STREAM_ID"] = str(log_stream_id)
    else:
        for k in ("GALILEO_PROJECT_ID", "GALILEO_LOG_STREAM_ID"):
            os.environ.pop(k, None)
    return {
        "project": project,
        "log_stream": log_stream,
        "project_id": project_id,
        "log_stream_id": log_stream_id,
    }


def clear_active_target() -> bool:
    """Delete the persisted live target so the app reverts to the .env default
    on the next restart. Returns True if a file was removed."""
    try:
        os.remove(_ACTIVE_TARGET_FILE)
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


def apply_live_target(
    project_name: str,
    log_stream_name: str,
    *,
    project_id: Optional[str] = None,
    log_stream_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Repoint the running process so all *subsequent* live traces log to this
    project/log stream, overriding the startup GALILEO_PROJECT / GALILEO_LOG_STREAM.

    Why env vars are enough: the runner always calls the Galileo logger with
    ``project=None`` / ``log_stream=None``. The SDK's logger singleton resolves
    those from ``GALILEO_PROJECT`` / ``GALILEO_LOG_STREAM`` at trace time and
    keys its logger cache by the resolved names, so flipping the env vars makes
    the next trace build a fresh logger bound to the new target. Env is
    process-global, so this holds across every request/thread — no restart.

    When ``project_id`` / ``log_stream_id`` are supplied we pin them in the
    environment so Agent Control binds to the *exact* injected stream instead of
    re-resolving by name (which is ambiguous when two streams share a name and
    can otherwise land AC on a different stream than the control).

    We also reset the console-link cache, terminate cached loggers so nothing
    keeps writing to the old stream, and re-point Agent Control so the steer
    control guards live chat too. All best-effort; never raises.
    """
    result: Dict[str, Any] = {
        "status": "active",
        "project": project_name,
        "log_stream": log_stream_name,
        "log_stream_id": log_stream_id,
    }

    os.environ["GALILEO_PROJECT"] = project_name
    os.environ["GALILEO_LOG_STREAM"] = log_stream_name
    if project_id and log_stream_id:
        # Pin the exact target so AC binds to the same stream traffic lands in.
        os.environ["GALILEO_PROJECT_ID"] = project_id
        os.environ["GALILEO_LOG_STREAM_ID"] = log_stream_id
    else:
        for k in ("GALILEO_PROJECT_ID", "GALILEO_LOG_STREAM_ID"):
            os.environ.pop(k, None)

    # Console deep-link IDs are cached off the old names — force a re-resolve.
    try:
        import app.galileo_links as _links
        _links._console_ids_cache = {}
    except Exception as e:  # noqa: BLE001
        result["console_cache_error"] = str(e)

    # Terminate every cached logger so none keeps writing to the old stream;
    # the next trace rebuilds one against the new env target.
    try:
        from galileo.utils.singleton import GalileoLoggerSingleton
        GalileoLoggerSingleton().reset_all()
        result["logger_reset"] = True
    except Exception as e:  # noqa: BLE001
        result["logger_reset_error"] = str(e)

    # Best-effort: make the steer control follow the app to the new log stream.
    try:
        from app.agent_control_setup import repoint_agent_control
        result["agent_control"] = repoint_agent_control()
    except Exception as e:  # noqa: BLE001
        result["agent_control_error"] = str(e)

    # Persist so this target survives a process restart (uvicorn --reload /
    # container restart), where load_dotenv would otherwise revert to .env.
    persist_err = _persist_active_target(project_name, log_stream_name, project_id, log_stream_id)
    if persist_err:
        result["persist_error"] = persist_err
    else:
        result["persisted"] = True

    return result


def provision_promo_demo(
    project_name: str,
    log_stream_name: str,
    *,
    mistakes_per_hour: float = 10.0,
    hours: float = 3.0,
    correct_per_hour: float = 6.0,
    spread_days: float = 21.0,
    tz_name: str = "America/Los_Angeles",
    create_metric: bool = True,
    create_control: bool = True,
    set_active: bool = True,
) -> Dict[str, Any]:
    """Provision a fresh promo demo project. Blocking; run in a thread.

    Steps (all best-effort, reported independently):
      1. Create project + log stream (idempotent).
      2. Enable the demo metric set on the stream (expired-promo-applied +
         customer-sentiment + 6 presets) BEFORE injecting, so metrics score the
         arriving traces. (``create_metric``)
      3. Attach the ``promo-proposal-steer`` control to the stream, DISABLED
         (``create_control``).
      4. Inject the promo traffic. Session COUNT still comes from
         ``mistakes_per_hour``/``correct_per_hour`` × ``hours``, but the
         timestamps are spread across the last ``spread_days`` with realistic
         webstore seasonality (busier evenings/lunch + weekends).
      5. Repoint the live app at this project/stream (``set_active``).
    """
    project_name = (project_name or "").strip()
    log_stream_name = (log_stream_name or "").strip()
    if not project_name or not log_stream_name:
        raise ValueError("project_name and log_stream_name are required")

    # Final backstop on trace volume even if a caller bypasses the API layer:
    # clamp the window so total sessions stay under MAX_SESSIONS.
    per_hour = max(1.0, float(mistakes_per_hour) + float(correct_per_hour))
    hours = max(0.1, min(float(hours), MAX_SESSIONS / per_hour))

    steps: Dict[str, Any] = {}

    steps["project"] = _ensure_project(project_name)
    project_id = steps["project"].get("id")
    if steps["project"].get("status") == "error" or not project_id:
        return {
            "ok": False,
            "project_name": project_name,
            "log_stream_name": log_stream_name,
            "error": steps["project"].get("error", "could not resolve project id"),
            "steps": steps,
        }

    log_stream, ls_status = _ensure_log_stream(project_name, log_stream_name, project_id=project_id)
    steps["log_stream"] = ls_status
    log_stream_id = ls_status.get("id")
    if log_stream is None or not log_stream_id:
        return {
            "ok": False,
            "project_name": project_name,
            "log_stream_name": log_stream_name,
            "error": ls_status.get("error", "could not create/resolve log stream"),
            "steps": steps,
        }

    if create_metric:
        steps["metric"] = _ensure_metric(log_stream)
    else:
        steps["metric"] = {"status": "skipped"}

    if create_control:
        steps["steer_control"] = _ensure_steer_control(log_stream_id)
    else:
        steps["steer_control"] = {"status": "skipped"}

    # Inject last so the project/stream exist and are fully wired first.
    from inject_promo_sessions import inject_sessions

    injection = inject_sessions(
        project_name,
        log_stream_name,
        mistakes_per_hour=mistakes_per_hour,
        hours=hours,
        correct_per_hour=correct_per_hour,
        spread_days=spread_days,
        tz_name=tz_name,
    )
    steps["injection"] = {"status": "ok", **injection}

    # Repoint the live app last, once everything is wired, so subsequent manual
    # chat traces log to this project/stream and the steer control guards them.
    if set_active:
        steps["set_active"] = apply_live_target(
            project_name,
            log_stream_name,
            project_id=project_id,
            log_stream_id=log_stream_id,
        )
    else:
        steps["set_active"] = {"status": "skipped"}

    console = os.environ.get("GALILEO_CONSOLE_URL", "").rstrip("/") or None
    return {
        "ok": True,
        "project_name": project_name,
        "log_stream_name": log_stream_name,
        "console_url": console,
        "metric_name": PROMO_METRIC_NAME if create_metric else None,
        "metric_names": (
            [PROMO_METRIC_NAME, CUSTOMER_SENTIMENT_METRIC_NAME, *PRESET_METRIC_NAMES]
            if create_metric else None
        ),
        "steer_control_name": STEER_CONTROL_NAME if create_control else None,
        "active_target": set_active,
        "steps": steps,
    }
