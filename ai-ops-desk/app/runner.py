"""
Shared runner for the AI Operations Desk multi-agent graph.

Used by both the CLI (main.py) and the FastAPI backend (app/api.py).
"""
import json
import time
from typing import Any, AsyncIterator, Dict, List, Optional

from galileo import galileo_context, log

from app.graph import create_ops_desk_graph
from app.toggles import ToggleManager
from app.galileo_links import galileo_session_url
from app.agent_control_setup import init_agent_control


# Cache the compiled graph at module scope. Keeps `graph` out of
# `_invoke_graph`'s signature so @log only captures `state` as the span
# input (the LangGraph object is huge and would bloat every trace).
_graph = None


async def _get_graph():
    global _graph
    if _graph is None:
        # Initialize Agent Control once on first use. This connects to the
        # control plane and pulls down the current set of controls associated
        # with this agent (e.g. block-zero-refund).
        init_agent_control()
        _graph = await create_ops_desk_graph()
    return _graph


@log(span_type="workflow", name="ops_desk_run")
async def _invoke_graph(state: Dict[str, Any]) -> Dict[str, Any]:
    """Parent workflow span that wraps the graph run so all node spans
    nest under a single trace instead of creating sibling traces."""
    graph = await _get_graph()
    return await graph.ainvoke(state)


def _apply_toggles(toggles_provided: Optional[List[str]]) -> ToggleManager:
    toggles = ToggleManager()
    if toggles_provided and "drift" in toggles_provided:
        toggles.policy_force_old_version = True
    return toggles


def _initial_state(
    user_query: str,
    user_id: str,
    scenario: str = "freeform",
    chat_session_id: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "user_query": user_query,
        "user_id": user_id,
        "scenario": scenario,
        "chat_session_id": chat_session_id,
    }


def _attach_session_id(result: Dict[str, Any]) -> Dict[str, Any]:
    logger = galileo_context.get_logger_instance()
    if logger and logger.session_id:
        result["galileo_session_id"] = logger.session_id
    return result


def _promo_trace_metadata(state: Dict[str, Any]) -> Dict[str, str]:
    """Pull applied-discount fields off the apply_discount receipt.

    We attach these to the *trace root* (see `_attach_trace_metadata`) because
    the Console's trace-table column selector can only surface **trace-level**
    metadata — deep span metadata (on the Apply Discount span) can't be shown
    as a column. Values are flat strings, comma-free, so `discount_usd` sorts
    and filters as a number.
    """
    action = state.get("action_output")
    receipts = getattr(action, "tool_receipts", None) if action else None
    if not receipts:
        return {}

    # Turn 2 (apply): the apply_discount receipt carries what was actually
    # applied (or attempted, when blocked) plus the list price.
    for r in receipts:
        if getattr(r, "tool", None) != "apply_discount":
            continue
        resp = getattr(r, "response", None) or {}
        md: Dict[str, str] = {
            "discount_usd": f"{float(resp.get('discount_usd', 0.0) or 0.0):.2f}",
            "list_price": f"{float(resp.get('list_price', 0.0) or 0.0):.2f}",
            "promo_expired": str(resp.get("promo_expired", False)).lower(),
            "apply_status": str(getattr(r, "status", "")),
        }
        if resp.get("promo_code"):
            md["promo_code"] = str(resp["promo_code"])
        if resp.get("promo_end_date"):
            md["promo_end_date"] = str(resp["promo_end_date"])
        if "attempted_discount_usd" in resp:
            md["attempted_discount_usd"] = f"{float(resp.get('attempted_discount_usd', 0.0) or 0.0):.2f}"
        return md

    # Turn 1 (proposal): no apply yet, so surface the *proposed* discount and
    # the list price off the check_promotions receipt. Without this the
    # "any discount?" turn shows no $ columns in the Console trace table.
    for r in receipts:
        if getattr(r, "tool", None) != "check_promotions":
            continue
        resp = getattr(r, "response", None) or {}
        md = {
            "discount_usd": f"{float(resp.get('proposed_discount_usd', 0.0) or 0.0):.2f}",
            "list_price": f"{float(resp.get('list_price', 0.0) or 0.0):.2f}",
            "promo_expired": str(resp.get("proposed_promo_expired", False)).lower(),
            "promo_stage": "proposed",
        }
        if resp.get("proposed_promo_code"):
            md["promo_code"] = str(resp["proposed_promo_code"])
        if resp.get("proposed_promo_end_date"):
            md["promo_end_date"] = str(resp["proposed_promo_end_date"])
        if resp.get("no_active_promo"):
            md["no_active_promo"] = "true"
        return md

    return {}


def _attach_trace_metadata(md: Dict[str, str], trace: Any = None) -> None:
    """Best-effort merge of trace-level metadata onto the current (or given)
    trace before it's flushed. Never raises — logging must not break a run."""
    if not md:
        return
    try:
        target = trace if trace is not None else galileo_context.get_current_trace()
        if target is not None:
            existing = dict(getattr(target, "user_metadata", None) or {})
            existing.update(md)
            target.user_metadata = existing
    except Exception:
        pass


def _start_session(scenario: str, chat_session_id: Optional[str] = None) -> Optional[str]:
    """Explicitly start (or resume) a Galileo session.

    When ``chat_session_id`` is provided, we pass it as the Galileo session's
    ``external_id``. The SDK's start_session will return the existing session
    if one already exists for this external_id (see Logger.start_session),
    which is exactly what we want for a chat conversation that spans many
    backend requests: every turn in the same chat ends up under one Galileo
    session, so metrics (e.g. refund-compliance) can correlate the receipt
    request and the refund request that followed it.

    Returns None if Galileo isn't configured.
    """
    try:
        if chat_session_id:
            return galileo_context.start_session(
                name=f"ops-desk:{scenario}",
                external_id=chat_session_id,
            )
        return galileo_context.start_session(name=f"ops-desk:{scenario}")
    except Exception:
        return None


async def run_query(
    user_query: str,
    user_id: str,
    toggles: Optional[List[str]] = None,
    scenario: str = "freeform",
    chat_session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the agent graph and return the final state."""
    _apply_toggles(toggles)
    session_id = _start_session(scenario, chat_session_id)
    result = await _invoke_graph(_initial_state(user_query, user_id, scenario, chat_session_id))
    if session_id and not result.get("galileo_session_id"):
        result["galileo_session_id"] = session_id
    _attach_session_id(result)
    _attach_trace_metadata(_promo_trace_metadata(result))
    galileo_context.flush()
    return result


async def stream_query(
    user_query: str,
    user_id: str,
    toggles: Optional[List[str]] = None,
    scenario: str = "freeform",
    chat_session_id: Optional[str] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """
    Run the agent graph and yield events as each node completes.

    Event shape:
      { "type": "agent_done", "agent": "<name>", "elapsed_ms": <int> }
      { "type": "complete", "result": {...} }
      { "type": "error", "message": "..." }
    """
    _apply_toggles(toggles)
    session_id = _start_session(scenario, chat_session_id)
    graph = await _get_graph()
    state = _initial_state(user_query, user_id, scenario, chat_session_id)

    # Manually open a parent workflow trace so each node @log span nests
    # under one trace instead of producing siblings. We can't use the @log
    # decorator here because this function is an async generator; the SDK's
    # context lookup still finds this trace via the active client instance.
    logger = galileo_context.get_logger_instance()
    parent_trace = None
    if logger is not None:
        try:
            parent_trace = logger.start_trace(
                input=json.dumps(state, default=str),
                name="ops_desk_run",
            )
        except Exception:
            parent_trace = None

    final_state: Dict[str, Any] = {}
    if session_id:
        final_state["galileo_session_id"] = session_id
    node_started_at = time.time()
    error_msg: Optional[str] = None

    try:
        async for chunk in graph.astream(state, stream_mode="updates"):
            # chunk is { node_name: <state delta from that node> }
            for node_name, node_state in chunk.items():
                elapsed_ms = int((time.time() - node_started_at) * 1000)
                yield {
                    "type": "agent_done",
                    "agent": node_name,
                    "elapsed_ms": elapsed_ms,
                }
                node_started_at = time.time()
                if isinstance(node_state, dict):
                    final_state.update(node_state)
    except Exception as e:
        error_msg = str(e)
        yield {"type": "error", "message": error_msg}
    finally:
        if parent_trace is not None and logger is not None:
            # Attach applied-discount fields to the trace root so they can be
            # enabled as columns in the Console trace table.
            _attach_trace_metadata(_promo_trace_metadata(final_state), parent_trace)
            try:
                logger.conclude(
                    output=error_msg or final_state.get("status", "completed"),
                )
            except Exception:
                pass

    if error_msg:
        return

    _attach_session_id(final_state)
    try:
        galileo_context.flush()
    except Exception:
        pass
    yield {"type": "complete", "result": serialize_result(final_state)}


def serialize_result(state: Dict[str, Any]) -> Dict[str, Any]:
    """Convert the LangGraph final state into a JSON-serializable response."""
    audit = state.get("audit_output")
    action = state.get("action_output")

    rationale = getattr(audit, "rationale", None) if audit else None

    actions: List[Dict[str, Any]] = []
    if action and getattr(action, "tool_receipts", None):
        for receipt in action.tool_receipts:
            actions.append({
                "tool": receipt.tool,
                "status": receipt.status,
                "ok": 200 <= receipt.status < 300,
                "response": receipt.response,
            })

    return {
        "status": state.get("status", "unknown"),
        "error": state.get("error"),
        "reply": state.get("customer_reply"),
        "rationale": rationale,
        "actions": actions,
        "resolution": getattr(action, "resolution", None) if action else None,
        "galileo_session_id": state.get("galileo_session_id"),
        "galileo_session_url": galileo_session_url(state.get("galileo_session_id")),
    }


