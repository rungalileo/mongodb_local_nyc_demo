# AI Ops Desk — Web Frontend

Next.js 16 + Tailwind UI for the AI Operations Desk demo. Talks to the
FastAPI backend in `../ai-ops-desk` over SSE.

## Running

1. Start the backend (in `../ai-ops-desk`):
   ```bash
   source .venv/bin/activate
   uvicorn app.api:app --reload --port 8000
   ```

2. Start the frontend:
   ```bash
   cp .env.local.example .env.local   # edit if backend isn't on :8000
   npm install
   npm run dev
   ```

3. Open http://localhost:3000.

## What you can do

- Pick a seeded user, type a free-form query, hit **Run workflow**.
- Watch each agent (Records → Policy → Action → Audit) tick green as it finishes.
- See the audit rationale + tools the action agent fired.
- Click **View session in Galileo** to inspect the trace in the Galileo console.
- Toggle **drift** to force the policy agent to use an old policy version.

## Endpoints consumed

- `GET  /api/users`         — user dropdown
- `GET  /api/scenarios`     — example chips
- `POST /api/chat/stream`   — SSE: `agent_done` × 4, then `complete`
