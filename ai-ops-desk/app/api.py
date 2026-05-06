"""
FastAPI backend for the AI Operations Desk demo.

Run with:
    uvicorn app.api:app --reload --port 8000
"""
import json
import os
from typing import List, Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.runner import run_query, stream_query, serialize_result
from app.scenarios import SCENARIOS
from app.rag.atlas_client import get_atlas_client


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


@app.get("/api/health")
async def health():
    return {"ok": True}


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


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Non-streaming: run the graph end-to-end and return the final result."""
    state = await run_query(
        user_query=req.user_query,
        user_id=req.user_id,
        toggles=req.toggles,
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
