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
from typing import Any, Dict, List, Optional

# Hard cap on injected traces. Each session is a real trace written to Galileo,
# so this bounds how long the button's request runs and how much it writes.
MAX_SESSIONS = int(os.getenv("PROMO_DEMO_MAX_SESSIONS", "500"))

# ---- LLM-as-judge metric --------------------------------------------------

PROMO_METRIC_NAME = os.getenv("PROMO_METRIC_NAME", "expired-promo-applied")

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

# Second trace-level judge: customer sentiment. Pairs with the expired-promo
# metric to tell the demo story — the bigger (expired) discounts delight the
# customer, so "positive sentiment" TRUE spikes on exactly the leaky traces.
SENTIMENT_METRIC_NAME = os.getenv("SENTIMENT_METRIC_NAME", "customer-positive-sentiment")

SENTIMENT_METRIC_PROMPT = (
    "You are auditing a single AI shopping-assistant conversation (one full "
    "trace). Classify the CUSTOMER's sentiment (not the assistant's tone) into "
    "exactly one of three labels: positive, neutral, or negative.\n\n"
    "Signals to use: the customer's own messages / reactions in the trace, and "
    "any sentiment fields exposed in the trace (e.g. a \"Classify Sentiment\" "
    "step output or `customer_sentiment` / `sentiment_score` metadata).\n\n"
    "Labels:\n"
    "- positive: the customer expresses delight, excitement, gratitude, or clear "
    "enthusiasm (for example, reacting happily to a discount or eagerly accepting "
    "an offer).\n"
    "- neutral: the customer is calm and matter-of-fact — just asking a question "
    "or acknowledging, with no strong feeling either way.\n"
    "- negative: the customer is annoyed, frustrated, dissatisfied, or upset.\n\n"
    "Respond with ONLY one word: positive, neutral, or negative. Judge only from "
    "the trace content."
)

# ---- Agent Control steer control -----------------------------------------

STEER_CONTROL_NAME = os.getenv("PROMO_STEER_CONTROL_NAME", "promo-selection-steer")

_STEER_MESSAGE = (
    "The promotion you selected is past its end date (expired). Do NOT propose or "
    "apply it. Re-select from the available promotions and consider ONLY offers "
    "whose end date is still in the future; if none are live, tell the customer "
    "there is no active promotion and keep full price."
)


def _steer_control_data() -> Dict[str, Any]:
    """Control definition for the promo-selection steer.

    Scope: the ``select_promotion`` guard step, POST stage — the point where the
    LLM has just chosen which promo to offer. The JSON evaluator fires
    (``matched=True``) when validation FAILS, so a schema that only passes when
    ``chosen_promo_expired`` is ``false`` triggers the steer precisely when the
    model picked an expired promo, turning it around to re-select a live one.
    """
    return {
        "description": (
            "Steer the agent when it selects an expired promo; re-select from "
            "currently-valid offers honoring the end date."
        ),
        "enabled": True,
        "execution": "server",
        "scope": {"step_names": ["select_promotion"], "stages": ["post"]},
        "condition": {
            "selector": {"path": "output"},
            "evaluator": {
                "name": "json",
                "config": {
                    "json_schema": {
                        "type": "object",
                        "required": ["chosen_promo_expired"],
                        "properties": {"chosen_promo_expired": {"const": False}},
                    }
                },
            },
        },
        "action": {
            "decision": "steer",
            "steering_context": {"message": _STEER_MESSAGE},
        },
        "tags": ["promo", "expired", "steer"],
    }


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


def _create_llm_judge(name: str, prompt: str, description: str, tags: List[str]) -> Dict[str, Any]:
    """Create one trace-level custom LLM-as-judge metric (idempotent)."""
    from galileo.metrics import create_custom_llm_metric
    from galileo.schema.metrics import StepType

    result: Dict[str, Any] = {"name": name}
    try:
        create_custom_llm_metric(
            name=name,
            user_prompt=prompt,
            node_level=StepType.trace,
            description=description,
            tags=tags,
        )
        result["created"] = True
    except Exception as e:  # already exists, or transient — enabling still works
        result["created"] = False
        result["create_note"] = f"{type(e).__name__}: {e}"
    return result


def _ensure_metric(log_stream) -> Dict[str, Any]:
    """Create the trace-level LLM judges (idempotent) and enable them on the
    stream. Two judges: the expired-promo flag and the customer-sentiment flag.
    """
    metrics = [
        _create_llm_judge(
            PROMO_METRIC_NAME,
            PROMO_METRIC_PROMPT,
            "Flags traces where the agent proposed or applied an expired/outdated promo.",
            ["promo", "expired"],
        ),
        _create_llm_judge(
            SENTIMENT_METRIC_NAME,
            SENTIMENT_METRIC_PROMPT,
            "Flags traces where the customer expresses positive sentiment (delight/enthusiasm).",
            ["promo", "sentiment"],
        ),
    ]
    result: Dict[str, Any] = {"name": PROMO_METRIC_NAME, "metrics": metrics}
    names = [PROMO_METRIC_NAME, SENTIMENT_METRIC_NAME]
    try:
        log_stream.enable_metrics(names)
        result["enabled"] = True
        result["enabled_metrics"] = names
        result["status"] = "ok"
    except Exception as e:
        result["enabled"] = False
        result["status"] = "enable_failed"
        result["error"] = f"{type(e).__name__}: {e}"
    return result


def _ensure_steer_control(log_stream_id: Optional[str]) -> Dict[str, Any]:
    """Create the steer control (idempotent) and bind it to the log stream.

    Uses the ACE REST API directly with the Galileo-API-Key header, mirroring
    ``agent_control_setup._manual_log_stream_binding_status``.
    """
    server_url = os.environ.get("AGENT_CONTROL_URL")
    api_key = os.environ.get("AGENT_CONTROL_API_KEY") or os.environ.get("GALILEO_API_KEY")
    api_key_header = os.environ.get("AGENT_CONTROL_API_KEY_HEADER", "Galileo-API-Key")

    result: Dict[str, Any] = {"name": STEER_CONTROL_NAME}
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
            create_resp = client.put(
                "/api/v1/controls",
                json={"name": STEER_CONTROL_NAME, "data": _steer_control_data()},
                headers=headers,
            )
            if create_resp.status_code == 409:
                # Already exists — look it up by name. NOTE: the list endpoint
                # rejects limit>100 with 422, so keep this at 100 (matches the
                # bindings endpoint cap). Using 200 here silently broke the
                # re-bind path: a pre-existing control never got its binding.
                result["created"] = False
                listing = client.get("/api/v1/controls", params={"limit": 100}, headers=headers)
                listing.raise_for_status()
                items = listing.json()
                items = items.get("controls", items) if isinstance(items, dict) else items
                for c in items or []:
                    if isinstance(c, dict) and c.get("name") == STEER_CONTROL_NAME:
                        control_id = c.get("id") or c.get("control_id")
                        break
            else:
                create_resp.raise_for_status()
                payload = create_resp.json()
                control_id = payload.get("control_id") or payload.get("id")
                result["created"] = True

            if control_id is None:
                result["status"] = "create_failed"
                result["error"] = "could not resolve control id"
                return result
            result["control_id"] = control_id

            bind_resp = client.put(
                "/api/v1/control-bindings/by-key",
                json={
                    "target_type": "log_stream",
                    "target_id": log_stream_id,
                    "control_id": control_id,
                    "enabled": True,
                },
                headers=headers,
            )
            bind_resp.raise_for_status()
            result["bound"] = True
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

    return result


def provision_promo_demo(
    project_name: str,
    log_stream_name: str,
    *,
    mistakes_per_hour: float = 10.0,
    hours: float = 3.0,
    correct_per_hour: float = 6.0,
    create_metric: bool = False,
    create_control: bool = False,
    set_active: bool = True,
) -> Dict[str, Any]:
    """Provision a fresh promo demo project. Blocking; run in a thread.

    By default this ONLY creates the project + log stream and injects traffic —
    the LLM-as-judge metric (eval) and the steer control are meant to be built
    by hand in the Console for a fresh org, so ``create_metric`` /
    ``create_control`` default to off.
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
        "metric_names": [PROMO_METRIC_NAME, SENTIMENT_METRIC_NAME] if create_metric else None,
        "steer_control_name": STEER_CONTROL_NAME if create_control else None,
        "active_target": set_active,
        "steps": steps,
    }
