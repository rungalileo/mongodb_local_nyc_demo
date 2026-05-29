"""
Agent Control initialization for the AI Ops Desk demo.

Supports two modes via the AGENT_CONTROL_MODE env var:

  - "enterprise" (default): Agent Control Enterprise (ACE), hosted inside
    the Galileo cluster. Controls live in Galileo Console and are bound to
    a log stream. Auth piggy-backs on GALILEO_API_KEY via the Galileo-API-Key
    header; the SDK exchanges that for a log-stream-scoped JWT per request.
    ControlExecutionEvents flow through the galileo SDK's auto-registered
    sink and become first-class `type=control` spans on the active trace.

  - "oss": self-hosted Agent Control server (e.g. docker compose locally,
    or a pinned image deployed elsewhere). Controls are created via
    setup_agent_control.py. Auth uses AGENT_CONTROL_API_KEY directly with
    the SDK's default header. No log-stream target binding.

Both modes share the same git-pinned `agent-control-sdk[galileo]` install
because that SDK is a strict superset of the OSS PyPI release; the only
difference is which kwargs we pass to `agent_control.init()`.

Common to both:
  - Idempotent and thread-safe (init runs exactly once per process).
  - Failures degrade gracefully: @control() decorators become no-ops and
    the demo keeps working without server-side controls.
"""
from __future__ import annotations

import logging
import os
from threading import Lock
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Use prints alongside the logger because uvicorn's default config does not
# attach a handler to the root logger -- silent init makes debugging painful.
def _say(msg: str) -> None:
    print(f"[agent_control] {msg}", flush=True)


_initialized: bool = False
_init_error: Optional[Exception] = None
_init_details: Dict[str, Any] = {}
_lock = Lock()


def _is_enabled() -> bool:
    return os.getenv("AGENT_CONTROL_ENABLED", "true").lower() not in ("0", "false", "no")


def _mode() -> str:
    """Return 'enterprise' (ACE, default) or 'oss' (self-hosted server)."""
    raw = os.environ.get("AGENT_CONTROL_MODE", "enterprise").strip().lower()
    if raw in ("enterprise", "ace", "ent"):
        return "enterprise"
    if raw in ("oss", "open-source", "open_source", "standalone", "self-hosted", "self_hosted"):
        return "oss"
    _say(f"unrecognized AGENT_CONTROL_MODE={raw!r}; defaulting to enterprise")
    return "enterprise"


def _resolve_ace_credentials() -> tuple[Optional[str], str]:
    """ACE uses GALILEO_API_KEY as the AC credential, sent in the
    `Galileo-API-Key` header by default."""
    api_key = os.environ.get("AGENT_CONTROL_API_KEY") or os.environ.get("GALILEO_API_KEY")
    if api_key and "AGENT_CONTROL_API_KEY" not in os.environ:
        os.environ["AGENT_CONTROL_API_KEY"] = api_key
    api_key_header = os.environ.get("AGENT_CONTROL_API_KEY_HEADER", "Galileo-API-Key")
    os.environ["AGENT_CONTROL_API_KEY_HEADER"] = api_key_header
    return api_key, api_key_header


def _resolve_log_stream_target() -> tuple[Optional[str], Optional[str]]:
    """Return (project_id, log_stream_id) for the configured project/log stream.

    We instantiate a GalileoLogger purely to resolve the IDs; this is the same
    pattern ace-demo uses. The logger is not retained -- the long-running
    process uses galileo_context for actual logging, which will reuse the
    cached IDs.
    """
    project = os.environ.get("GALILEO_PROJECT")
    log_stream = os.environ.get("GALILEO_LOG_STREAM")
    if not project or not log_stream:
        _say("GALILEO_PROJECT / GALILEO_LOG_STREAM not set; cannot resolve ACE log stream target.")
        return None, None
    try:
        from galileo.logger.logger import GalileoLogger
    except ImportError as e:
        _say(f"galileo SDK does not expose GalileoLogger ({e})")
        return None, None

    try:
        gl = GalileoLogger(project=project, log_stream=log_stream)
    except Exception as e:  # noqa: BLE001
        _say(f"Failed to resolve Galileo project/log stream IDs: {e}")
        return None, None

    if gl.project_id and gl.log_stream_id:
        # Galileo's Agent Control evaluator path expects this set.
        os.environ.setdefault("GALILEO_PROJECT_ID", gl.project_id)
    return gl.project_id, gl.log_stream_id


def init_agent_control() -> bool:
    """Initialize the Agent Control SDK. Safe to call multiple times.

    Dispatches on AGENT_CONTROL_MODE: enterprise (ACE, default) or oss
    (self-hosted standalone server). Returns True if AC is wired up.
    """
    global _initialized, _init_error, _init_details

    if _initialized:
        return True
    if not _is_enabled():
        _say("disabled via AGENT_CONTROL_ENABLED=false")
        _init_details = {"status": "disabled"}
        return False

    with _lock:
        if _initialized:
            return True

        try:
            import agent_control
        except ImportError as e:
            _say(f"SDK not installed ({e}); skipping init")
            _init_error = e
            _init_details = {"status": "sdk_missing", "error": str(e)}
            return False

        mode = _mode()
        _say(f"mode={mode}")
        if mode == "oss":
            return _init_oss(agent_control)
        return _init_enterprise(agent_control)


def _init_enterprise(agent_control) -> bool:
    """Initialize against Agent Control Enterprise (ACE).

    Resolves project_id/log_stream_id from Galileo, then calls init() with
    target_type=log_stream, the Galileo-API-Key header, JWT runtime auth, and
    observability_sink_name=registered so the galileo bridge picks up
    ControlExecutionEvents and writes them as ControlSpans.
    """
    global _initialized, _init_error, _init_details

    agent_name = os.environ.get("AGENT_CONTROL_AGENT_NAME", "ai-ops-desk")
    server_url = os.environ.get("AGENT_CONTROL_URL")
    if not server_url:
        _say("AGENT_CONTROL_URL not set; cannot init ACE")
        _init_details = {"status": "no_server_url", "mode": "enterprise"}
        return False

    api_key, api_key_header = _resolve_ace_credentials()
    runtime_auth_mode = os.environ.get("AGENT_CONTROL_RUNTIME_AUTH_MODE", "jwt")
    target_type = os.environ.get("AGENT_CONTROL_TARGET_TYPE", "log_stream")

    project_id, log_stream_id = _resolve_log_stream_target()
    if not log_stream_id:
        _say(
            "could not resolve Galileo log_stream_id; init skipped. "
            "Verify GALILEO_PROJECT/GALILEO_LOG_STREAM/GALILEO_API_KEY/GALILEO_API_URL."
        )
        _init_details = {"status": "no_log_stream_id", "mode": "enterprise"}
        return False

    refresh_interval = _refresh_interval()

    _say(
        f"initializing (enterprise): agent={agent_name} server={server_url} "
        f"target={target_type}:{log_stream_id} auth={runtime_auth_mode} "
        f"refresh={refresh_interval}s"
    )

    try:
        agent_control.init(
            agent_name=agent_name,
            agent_description="AI Ops Desk multi-agent customer support demo",
            server_url=server_url,
            api_key=api_key,
            api_key_header=api_key_header,
            target_type=target_type,
            target_id=log_stream_id,
            runtime_auth_mode=runtime_auth_mode,
            # "registered" tells the SDK to use whichever sink the host
            # process registered. The galileo SDK auto-registers its
            # AC bridge sink on import, so this routes ControlExecutionEvents
            # straight to the active Galileo trace as ControlSpans.
            observability_enabled=True,
            observability_sink_name="registered",
            policy_refresh_interval_seconds=refresh_interval,
        )
        _initialized = True
        _init_details = {
            "status": "initialized",
            "mode": "enterprise",
            "agent_name": agent_name,
            "server_url": server_url,
            "target_type": target_type,
            "target_id": log_stream_id,
            "project_id": project_id,
            "runtime_auth_mode": runtime_auth_mode,
            "refresh_interval_seconds": refresh_interval,
        }
        _say(f"✓ initialized (enterprise, target={target_type}:{log_stream_id})")
        return True
    except Exception as e:  # noqa: BLE001
        _init_error = e
        _init_details = {
            "status": "init_failed",
            "mode": "enterprise",
            "error": str(e),
            "error_type": type(e).__name__,
        }
        import traceback
        _say(f"✗ ACE init failed ({type(e).__name__}): {e}")
        traceback.print_exc()
        return False


def _init_oss(agent_control) -> bool:
    """Initialize against a self-hosted standalone Agent Control server.

    No log-stream target. Auth uses AGENT_CONTROL_API_KEY directly with the
    SDK's default header. Controls are managed via setup_agent_control.py
    against the same server.
    """
    global _initialized, _init_error, _init_details

    agent_name = os.environ.get("AGENT_CONTROL_AGENT_NAME", "ai-ops-desk")
    server_url = os.environ.get("AGENT_CONTROL_URL", "http://localhost:8000")
    api_key = os.environ.get("AGENT_CONTROL_API_KEY") or None
    refresh_interval = _refresh_interval()

    _say(
        f"initializing (oss): agent={agent_name} server={server_url} "
        f"api_key={'set' if api_key else 'unset'} refresh={refresh_interval}s"
    )

    try:
        agent_control.init(
            agent_name=agent_name,
            agent_description="AI Ops Desk multi-agent customer support demo",
            server_url=server_url,
            api_key=api_key,
            observability_enabled=True,
            policy_refresh_interval_seconds=refresh_interval,
        )
        _initialized = True
        _init_details = {
            "status": "initialized",
            "mode": "oss",
            "agent_name": agent_name,
            "server_url": server_url,
            "refresh_interval_seconds": refresh_interval,
        }
        _say(f"✓ initialized (oss, server={server_url})")
        return True
    except Exception as e:  # noqa: BLE001
        _init_error = e
        _init_details = {
            "status": "init_failed",
            "mode": "oss",
            "error": str(e),
            "error_type": type(e).__name__,
        }
        import traceback
        _say(f"✗ OSS init failed ({type(e).__name__}): {e}")
        traceback.print_exc()
        return False


def _refresh_interval() -> int:
    try:
        return int(os.environ.get("AGENT_CONTROL_REFRESH_INTERVAL_SECONDS", "5"))
    except ValueError:
        return 5


def agent_control_status() -> Dict[str, Any]:
    """Snapshot of init state — exposed via /api/agent_control/status for debug."""
    info: Dict[str, Any] = {
        "initialized": _initialized,
        "enabled": _is_enabled(),
        "details": dict(_init_details),
    }
    if _init_error is not None:
        info["init_error"] = f"{type(_init_error).__name__}: {_init_error}"

    # Try to introspect the running SDK for bound controls. The SDK's API
    # varies between versions; we probe a few common attribute names and
    # skip anything that returns a coroutine (we'd need an event loop).
    try:
        import inspect
        import agent_control
        bound = []
        for attr in ("list_controls", "get_controls", "registered_controls", "controls"):
            val = getattr(agent_control, attr, None)
            if val is None:
                continue
            if callable(val):
                if inspect.iscoroutinefunction(val):
                    continue
                try:
                    val = val()
                except Exception:
                    continue
            if inspect.iscoroutine(val):
                continue
            try:
                bound = list(val)
                break
            except TypeError:
                continue
        info["controls"] = [str(c) for c in bound]
    except Exception as e:  # noqa: BLE001
        info["controls_error"] = f"{type(e).__name__}: {e}"

    return info


async def shutdown_agent_control() -> None:
    """Flush pending observability events. Safe to call even if init failed."""
    if not _initialized:
        return
    try:
        import agent_control
        await agent_control.ashutdown()
    except Exception as e:  # noqa: BLE001
        logger.debug("agent_control shutdown error: %s", e)
