"""
FastAPI backend for the AI Operations Desk demo.

Run with:
    uvicorn app.api:app --reload --port 8000
"""
import asyncio
import json
import os
from typing import List, Optional

from dotenv import load_dotenv
# override=True so the .env file is authoritative even if the shell has
# stale exports (e.g. AGENT_CONTROL_URL left over from a previous local
# AC server run). Without this, exported shell vars silently shadow .env.
load_dotenv(override=True)

# Trust the OS certificate store before any HTTPS client is built (fixes
# corporate TLS-interception breaking OpenAI calls). Safe no-op otherwise.
import app.tls_trust  # noqa: F401,E402

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.runner import run_query, stream_query, serialize_result
from app.scenarios import SCENARIOS
from app.rag.atlas_client import get_atlas_client
from app.agent_control_setup import init_agent_control, agent_control_status

# Re-apply the last provisioned live target (if any) OVER the .env defaults, so
# a project created via the Ops button stays associated across restarts /
# --reload instead of snapping back to GALILEO_PROJECT from .env.
from app.promo_demo_provision import restore_active_target
_restored_target = restore_active_target()
if _restored_target:
    print(f"[startup] restored live target → project={_restored_target['project']!r} "
          f"log_stream={_restored_target['log_stream']!r}")


app = FastAPI(title="AI Operations Desk API")

# Comma-separated list of allowed origins. Falls back to localhost for dev.
# In prod, set ALLOWED_ORIGINS to your frontend domain(s), e.g.
#   ALLOWED_ORIGINS=https://cisco-demo-frontend.up.railway.app
_origins_env = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
_allowed_origins = [o.strip() for o in _origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    user_query: str
    user_id: str
    toggles: Optional[List[str]] = None
    # Stable per-chat identifier from the frontend. When present, every turn
    # in the same chat is recorded under one Galileo session (via external_id),
    # which lets session-level metrics (e.g. refund compliance) see the full
    # conversation. Omit to get the legacy "one session per request" behavior.
    chat_session_id: Optional[str] = None


class PromoDemoRequest(BaseModel):
    """Ops-view request to spin up a fresh promo demo project.

    The button only asks for a project + log stream name; the traffic rate has
    sensible defaults (~10 expired-promo mistakes/hour over 3 hours of COUNT),
    spread across the last ``spread_days`` with realistic webstore seasonality.
    By default it also enables the demo metric set and attaches the (disabled)
    steer control before injecting.
    """
    project_name: str
    log_stream_name: str = "Default"
    mistakes_per_hour: float = 10.0
    hours: float = 3.0
    correct_per_hour: float = 6.0
    # Spread the injected sessions across the last N days (seasonal shape).
    spread_days: float = 21.0
    tz_name: str = "America/Los_Angeles"
    # Enable the demo metric set and attach the disabled steer control by default.
    create_metric: bool = True
    create_control: bool = True
    # When true, repoint the live app at the new project/log stream so all
    # subsequent manual chat traces log there (overriding the env project).
    set_active: bool = True


class CostDemoRequest(BaseModel):
    """Ops-view request to extend the Integration-cost demo curves.

    Everything defaults: leave start/end blank to continue each project's cost
    curve from the last day it dropped to $0 up to now. The phased job sets the
    evaluator model price to $1,830 (LLM_Evals) then $80 (Luna_Evals), injects
    identical-timestamp traffic into each, waits for scoring, then removes the
    price override.
    """
    start: Optional[str] = None
    end: Optional[str] = None
    tz_name: str = "America/Los_Angeles"
    seed: int = 7
    # Leave blank to target the real LLM_Evals / Luna_Evals projects. Set to
    # throwaway names to test the flow against disposable projects.
    llm_project: Optional[str] = None
    luna_project: Optional[str] = None
    llm_price: Optional[float] = None
    luna_price: Optional[float] = None


class CostDemoDeleteRequest(BaseModel):
    """Delete throwaway test projects created by a cost-demo test run. The real
    LLM_Evals / Luna_Evals projects are protected and cannot be deleted here."""
    names: List[str]


class CostDemoFixRequest(BaseModel):
    """Heal scoring gaps (e.g. a $0 day from an evaluator system error). Scans
    BOTH projects and re-injects whichever dipped at its correct frozen price
    (LLM_Evals @ $1,830, Luna_Evals @ $80). Leave start/end blank to auto-detect
    the broken window per project; pass throwaway names to heal sandbox projects."""
    llm_project: Optional[str] = None
    luna_project: Optional[str] = None
    llm_price: Optional[float] = None
    luna_price: Optional[float] = None
    start: Optional[str] = None
    end: Optional[str] = None
    tz_name: str = "America/Los_Angeles"
    seed: int = 7


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/agent_control/status")
async def agent_control_status_endpoint():
    """Debug snapshot of Agent Control init state.

    Forces an init attempt if it hasn't run yet, then reports back what the
    SDK looks like — whether it's wired up, what target it's bound to, and
    any controls it has loaded. Use this when controls aren't showing up to
    figure out whether init ran, failed, or succeeded-but-bound-nothing.
    """
    init_agent_control()
    return agent_control_status()


@app.get("/api/users")
async def list_users():
    """Return seeded user IDs from the orders collection."""
    try:
        client = get_atlas_client()
        user_ids = sorted(client.db.orders.distinct("user_id"))
        return {"users": [{"id": uid} for uid in user_ids]}
    except Exception as e:
        # Fallback: derive from scenarios so the UI still works.
        fallback = sorted({s["user_id"] for s in SCENARIOS.values()})
        return {"users": [{"id": uid} for uid in fallback], "error": str(e)}


@app.get("/api/scenarios")
async def list_scenarios():
    return {
        "scenarios": [
            {"name": name, **payload} for name, payload in SCENARIOS.items()
        ]
    }


@app.post("/api/ops/promo_demo")
async def create_promo_demo(req: PromoDemoRequest):
    """Provision a fresh promo demo project (project + log stream + injected
    traffic at ~N expired-promo mistakes/hour).

    The eval metric and steer control are built by hand in the Console, so this
    defaults to just creating the project/stream and seeding traffic. Blocking
    work (network calls + trace injection) runs in a worker thread so the event
    loop stays responsive. Each sub-step reports its own status, so a partial
    success still returns 200 with details rather than failing the whole call.
    """
    from app.promo_demo_provision import provision_promo_demo

    try:
        result = await asyncio.to_thread(
            provision_promo_demo,
            req.project_name,
            req.log_stream_name,
            mistakes_per_hour=req.mistakes_per_hour,
            hours=req.hours,
            correct_per_hour=req.correct_per_hour,
            spread_days=req.spread_days,
            tz_name=req.tz_name,
            create_metric=req.create_metric,
            create_control=req.create_control,
            set_active=req.set_active,
        )
        return result
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@app.post("/api/ops/cost_demo")
async def start_cost_demo_endpoint(req: CostDemoRequest):
    """Kick off the phased Integration-cost injection (LLM_Evals + Luna_Evals).

    Returns immediately; the work runs in a background thread because it sets
    org-wide model prices and waits for async scoring between the two projects.
    Poll ``GET /api/ops/cost_demo/status`` for progress.
    """
    from app.cost_demo_provision import start_cost_demo

    try:
        return start_cost_demo(
            start=req.start,
            end=req.end,
            tz_name=req.tz_name,
            seed=req.seed,
            llm_project=req.llm_project,
            luna_project=req.luna_project,
            llm_price=req.llm_price,
            luna_price=req.luna_price,
        )
    except Exception as e:
        return {"started": False, "reason": f"{type(e).__name__}: {e}"}


@app.get("/api/ops/cost_demo/status")
async def cost_demo_status_endpoint():
    """Progress snapshot for the running/last Integration-cost injection."""
    from app.cost_demo_provision import get_cost_demo_status

    return get_cost_demo_status()


@app.post("/api/ops/cost_demo/fix")
async def cost_demo_fix_endpoint(req: CostDemoFixRequest):
    """Heal scoring gaps for one project (delete + re-inject the broken window
    at the correct price). Runs in the background; poll the status endpoint."""
    from app.cost_demo_provision import start_cost_fix

    try:
        return start_cost_fix(
            llm_project=req.llm_project,
            luna_project=req.luna_project,
            llm_price=req.llm_price,
            luna_price=req.luna_price,
            start=req.start,
            end=req.end,
            tz_name=req.tz_name,
            seed=req.seed,
        )
    except Exception as e:
        return {"started": False, "reason": f"{type(e).__name__}: {e}"}


@app.post("/api/ops/cost_demo/delete")
async def cost_demo_delete_endpoint(req: CostDemoDeleteRequest):
    """Delete throwaway test projects (real LLM_Evals / Luna_Evals protected)."""
    from app.cost_demo_provision import delete_cost_demo_projects

    try:
        return await asyncio.to_thread(delete_cost_demo_projects, req.names)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Non-streaming: run the graph end-to-end and return the final result."""
    state = await run_query(
        user_query=req.user_query,
        user_id=req.user_id,
        toggles=req.toggles,
        chat_session_id=req.chat_session_id,
    )
    return serialize_result(state)


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE: emits one event per agent completion, then a final 'complete' event."""

    async def event_gen():
        try:
            async for event in stream_query(
                user_query=req.user_query,
                user_id=req.user_id,
                toggles=req.toggles,
                chat_session_id=req.chat_session_id,
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
