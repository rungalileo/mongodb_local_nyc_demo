# AI Operations Desk - Multi-Agent Demo

A sophisticated multi-agent AI system for handling customer service operations including refund requests, support tickets, and policy management.


<img src="image.png" alt="Multi-Agent Flow" width="600"/>


## Overview

This demo showcases:
- **Galileo** as an observability and evaluation tool
- **MongoDB Atlas** as a RAG store with Vector Search for policy retrieval
- **OpenAI** for LLM operations and embeddings
- **LangGraph** orchestration with 4 specialized agents
- **Other goodies:** Sturctured data models for compliance-y stuff, sentiment analysis and intent classification, the usual

## Architecture

### Agents
- **PolicyAgent (A1)**: Retrieves relevant policies using vector search
- **RecordsAgent (A3)**: Aggregates user's refund requests and support tickets
- **ActionAgent (A5)**: Executes tools based on user intent and sentiment
- **AuditAgent (A7)**: Provides comprehensive rationale and audit trail

### Data Models
- **Orders**: Product purchases with shipping details
- **Refund Requests**: Financial transactions for returns
- **Support Tickets**: Customer service interactions with sentiment tracking
- **Policies**: Versioned policy documents with effective dates

### Tools Available
- Create/Update support tickets
- Escalate tickets (for negative sentiment)
- Create refund requests
- Explain refund request status

## Prerequisites

- Python 3.11+
- MongoDB Atlas connection string
- OpenAI API key
- Galileo Account

## Quickstart

1. **Create and activate virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment**
   ```bash
   cp env.example .env
   # Edit .env with your MongoDB URI and OpenAI API key
   ```

4. **Set up data**
   ```bash
   python setup_policies.py
   python setup_orders.py
   python setup_refund_requests.py
   python setup_tickets.py
   ```

5. **Run scenarios (CLI)**
   ```bash
   python main.py --scenario refund_bluetooth_earbuds

   # OR to run the scenario by its number

   python main.py --index 0->6
   ```
   We also have a toggle manager to activate different failure states, but more on that later

6. **Run the API server (for the Next.js frontend)**
   ```bash
   uvicorn app.api:app --reload --port 8000
   ```
   Then start the frontend in `../ai-ops-desk-web` (`npm run dev`).
   Endpoints: `/api/health`, `/api/users`, `/api/scenarios`, `/api/chat`,
   `/api/chat/stream` (SSE — emits `agent_done` per node, then `complete`).

### Available Toggles
- **drift**: Simulates policy drift by forcing use of expired policies

## Agent Control (runtime guardrails)

The demo is wired up to [Agent Control](https://docs.agentcontrol.dev/) so you
can attach server-side guardrails to specific tool calls without changing
agent code.

### Start the control plane (local dev, no auth)

```bash
curl -L https://raw.githubusercontent.com/agentcontrol/agent-control/refs/heads/main/docker-compose.yml \
  | docker compose -f - up -d
```

This brings up Postgres and the Agent Control server at
`http://localhost:8000`. The dashboard UI is served by the same server
container — open `http://localhost:8000` in a browser to access it.

### Pinned image version

For anything beyond casual local hacking — and for **all Railway / prod
deploys** — pin the image version instead of `:latest`:

```
galileoai/agent-control-server:7.7.0
```

`:latest` can roll forward without warning. Pinning is what guarantees the
image you smoke-tested locally is bit-for-bit identical to what runs in prod.

### Test with auth locally (mirrors prod)

Before deploying anywhere customers can see, exercise the auth-protected
path on your laptop so a typo in env vars surfaces here, not on stage.

Three secrets do the work. What each is for:

| Value | What it does |
|---|---|
| **API key** (`AGENT_CONTROL_API_KEY`) | Sent by the SDK on every `@control()` call. Lower-privilege — can evaluate controls but cannot create or modify them. |
| **Admin key** (`AGENT_CONTROL_ADMIN_API_KEY`) | Used by `setup_agent_control.py` to create/attach controls, and by the dashboard at login. Never set on the long-running FastAPI process. |
| **Session secret** (`AGENT_CONTROL_SESSION_SECRET`) | Server-side HMAC key the Agent Control server uses to sign UI login sessions. Used by the server only. |

```bash
# 1. Generate keys + secret. Export them so docker compose inherits them
#    when we start the stack in step 2. Print them so you can copy the
#    values into ai-ops-desk/.env in step 3.
#
#    Note: the SDK uses singular names (AGENT_CONTROL_API_KEY) and the
#    server uses plural names (AGENT_CONTROL_API_KEYS). We export both.
export AGENT_CONTROL_API_KEY=$(uuidgen)
export AGENT_CONTROL_ADMIN_API_KEY=$(uuidgen)
export AGENT_CONTROL_SESSION_SECRET=$(openssl rand -hex 32)

export AGENT_CONTROL_API_KEY_ENABLED=true
export AGENT_CONTROL_API_KEYS="$AGENT_CONTROL_API_KEY"
export AGENT_CONTROL_ADMIN_API_KEYS="$AGENT_CONTROL_ADMIN_API_KEY"

cat <<EOF
─── Save these — you'll paste them into ai-ops-desk/.env below ───
AGENT_CONTROL_API_KEY=$AGENT_CONTROL_API_KEY
AGENT_CONTROL_ADMIN_API_KEY=$AGENT_CONTROL_ADMIN_API_KEY
AGENT_CONTROL_SESSION_SECRET=$AGENT_CONTROL_SESSION_SECRET
──────────────────────────────────────────────────────────────────
EOF

# 2. Stop any existing AC stack, then start a new one with auth ON.
#    The official compose file pins container names (agent_control_postgres,
#    agent_control_server), so we remove them by name. `docker compose down`
#    won't work here because we never wrote the compose file to disk.
docker rm -f agent_control_postgres agent_control_server 2>/dev/null
curl -L https://raw.githubusercontent.com/agentcontrol/agent-control/refs/heads/main/docker-compose.yml \
  | docker compose -f - up -d

# 2a. Verify the env actually made it into the container (sanity check —
#     this is the step that catches the "auth silently disabled" bug).
docker exec agent_control_server env | grep -E "^AGENT_CONTROL_(API_KEY|ADMIN|SESSION)"
# Expect: API_KEY_ENABLED=true, API_KEYS=<uuid>, ADMIN_API_KEYS=<uuid>,
# SESSION_SECRET=<hex>. If any are empty, step 1's exports didn't take —
# re-run them in the same shell and re-up.

# 3. Add these two lines to ai-ops-desk/.env (paste the values printed in step 1):
#      AGENT_CONTROL_API_KEY=<the first uuid>
#      AGENT_CONTROL_ADMIN_API_KEY=<the second uuid>

# 4. Re-run setup and the demo. Every request now carries X-API-Key under
#    the hood; behavior should otherwise be identical to the no-auth run.
python setup_agent_control.py
python main.py --index 0

# 5. Log into the dashboard at http://localhost:8000 with the admin key.
```

If the demo still blocks the $0 refund with auth on, you're prod-ready.

### Register the agent + create the "block zero refund" control

```bash
python setup_agent_control.py
```

This script:
1. Registers an agent named `ai-ops-desk` with the server.
2. Creates a control named `block-zero-refund` that uses the JSON evaluator
   to deny any `_create_refund_request` tool call whose returned `amount`
   is `0` (or missing).
3. Associates the control with the agent.

Re-running the script is idempotent — it will refresh the control definition
in place.

### How it's wired

- `app/agent_control_setup.py` lazily calls `agent_control.init()` the first
  time the LangGraph workflow runs.
- `app/agents/action.py` decorates `_create_refund_request` with `@control()`.
  The SDK sends the tool's output to the server, the server evaluates the
  JSON constraint `amount >= 0.01`, and a violation raises
  `ControlViolationError` inside `_execute_tool`.
- `_execute_tool` catches the violation and emits a `412` `ToolReceipt` so
  the rest of the workflow (audit + customer reply) keeps running and you
  can see exactly which control fired.

To disable the integration entirely (e.g. for CI), set
`AGENT_CONTROL_ENABLED=false` in your `.env`.

### Tweak or add controls

Open the UI at `http://localhost:8000` to flip controls on/off, change the
threshold, or add new ones (e.g. block refunds above some max). No code
redeploy needed — the SDK refreshes its cache from the server.

## Troubleshooting

- **MongoDB Connection**: Ensure your IP is whitelisted in Atlas
- **OpenAI API**: Verify your API key has sufficient credits
- **Vector Search**: Ensure the `policy_vectors` index is created in Atlas
- **Data Issues**: Run setup scripts to refresh data

## Development

The codebase uses:
- **Pydantic** for data validation and serialization
- **LangGraph** for agent orchestration
- **MongoDB Atlas** for data persistence and vector search
- **OpenAI** for LLM operations