"""
Galileo console deep-link helpers.

The Galileo console URL needs project + log-stream IDs (not names) in the
path. This module looks them up once via the SDK using the names from env
vars and caches them at module scope, then builds session URLs from them.
"""
import os
from typing import Dict, Optional


_console_ids_cache: Dict[str, Optional[str]] = {}


def _resolve_console_ids() -> Dict[str, Optional[str]]:
    """Resolve project + log-stream IDs from their names (cached per-process)."""
    global _console_ids_cache
    if _console_ids_cache:
        return _console_ids_cache

    project_name = os.getenv("GALILEO_PROJECT", "")
    log_stream_name = os.getenv("GALILEO_LOG_STREAM", "")
    project_id: Optional[str] = None
    log_stream_id: Optional[str] = None

    try:
        from galileo import projects, log_streams
        if project_name:
            proj = projects.get_project(name=project_name)
            project_id = getattr(proj, "id", None) if proj else None
        if project_id and log_stream_name:
            ls = log_streams.get_log_stream(name=log_stream_name, project_id=project_id)
            log_stream_id = getattr(ls, "id", None) if ls else None
    except Exception as e:
        print(f"  Galileo console ID lookup failed: {e}")

    _console_ids_cache = {"project_id": project_id, "log_stream_id": log_stream_id}
    return _console_ids_cache


def galileo_session_url(session_id: Optional[str]) -> Optional[str]:
    """Construct a deep link to the Galileo console for a given session.

    Returns None if the console URL isn't configured or if we can't resolve
    the project / log-stream IDs (rather than returning a broken link).
    """
    if not session_id:
        return None
    console = os.getenv("GALILEO_CONSOLE_URL", "").rstrip("/")
    if not console:
        return None
    ids = _resolve_console_ids()
    project_id = ids.get("project_id")
    log_stream_id = ids.get("log_stream_id")
    if not project_id or not log_stream_id:
        return None
    return f"{console}/project/{project_id}/log-stream/{log_stream_id}/session/{session_id}"
