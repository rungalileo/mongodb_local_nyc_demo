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
    sensible defaults (~10 expired-promo mistakes/hour over 3 hours). The eval
    metric and steer control are created by hand in the Console, so those
    default to off here.
    """
    project_name: str
    log_stream_name: str = "Default"
    mistakes_per_hour: float = 10.0
    hours: float = 3.0
    correct_per_hour: float = 6.0
    create_metric: bool = False
    create_control: bool = False
    # When true, repoint the live app at the new project/log stream so all
    # subsequent manual chat traces log there (overriding the env project).
    set_active: bool = True


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
            create_metric=req.create_metric,
            create_control=req.create_control,
            set_active=req.set_active,
        )
        return result
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


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
