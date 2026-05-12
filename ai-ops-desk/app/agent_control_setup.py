"""
Lazy initialization for the Agent Control SDK.

We init exactly once per process. If the server is unreachable, we degrade
gracefully: the @control() decorator becomes a no-op (the SDK logs a warning
and still runs the wrapped function) so the demo keeps working without the
control plane.
"""
import logging
import os
from threading import Lock
from typing import Optional

logger = logging.getLogger(__name__)

_initialized: bool = False
_init_error: Optional[Exception] = None
_lock = Lock()


def _is_enabled() -> bool:
    return os.getenv("AGENT_CONTROL_ENABLED", "true").lower() not in ("0", "false", "no")


def init_agent_control() -> bool:
    """Initialize the agent_control SDK. Safe to call multiple times.

    Returns True if the SDK is wired up (either already initialized or just
    initialized successfully), False otherwise.
    """
    global _initialized, _init_error

    if _initialized:
        return True
    if not _is_enabled():
        return False

    with _lock:
        if _initialized:
            return True

        try:
            import agent_control  # imported lazily so the dep is optional
        except ImportError as e:
            logger.warning("agent_control SDK not installed (%s); skipping init", e)
            _init_error = e
            return False

        # Hard-coded — see setup_agent_control.py for why we don't honor
        # AGENT_CONTROL_AGENT_NAME here (collision with the Cursor IDE hook).
        agent_name = "ai-ops-desk"
        server_url = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")
        # Read the API key here and pass it explicitly. The SDK can auto-read
        # AGENT_CONTROL_API_KEY from env via pydantic-settings, but only if
        # those settings haven't been cached before load_dotenv() ran. Passing
        # it explicitly removes that import-order foot-gun entirely.
        api_key = os.getenv("AGENT_CONTROL_API_KEY") or None
        # How often the SDK polls the server for control changes. The SDK
        # default is 60s, which is fine for prod but feels laggy during a
        # live "toggle the control in the UI and re-run" demo. 5s gives a
        # snappy demo without hammering the server.
        try:
            refresh_interval = int(os.getenv("AGENT_CONTROL_REFRESH_INTERVAL_SECONDS", "5"))
        except ValueError:
            refresh_interval = 5

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
            logger.info(
                "agent_control initialized for agent=%s server=%s api_key=%s refresh_every=%ss",
                agent_name,
                server_url,
                f"{api_key[:8]}…" if api_key else "<none>",
                refresh_interval,
            )
            return True
        except Exception as e:
            _init_error = e
            logger.warning(
                "agent_control init failed (%s); running without server-side controls. "
                "Start the server and rerun: docker compose up -d",
                e,
            )
            return False


async def shutdown_agent_control() -> None:
    """Flush pending observability events. Safe to call even if init failed."""
    if not _initialized:
        return
    try:
        import agent_control
        await agent_control.ashutdown()
    except Exception as e:
        logger.debug("agent_control shutdown error: %s", e)
