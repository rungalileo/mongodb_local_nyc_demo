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
   # Expired-promo demo (see EXPIRED_PROMO_DEMO.md):
   python setup_products.py
   python setup_promos.py
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

## Expired-Promo Use Case

A newer demo scenario: a customer shops for an expensive catalog item and asks
if there's a discount. The agent reads a **stale promo cache** that returns
offers whose end date has already passed, then applies one anyway and adds the
item to the cart — leaking margin. The applied discount dollar amount is logged
as span metadata (`discount_usd`), and a traffic generator makes it stay small
for the first N minutes then **spike**, so the anomaly is obvious in the Galileo
trace view.

Quick run:
```bash
python setup_products.py && python setup_promos.py
python main.py --scenario promo_oled_tv
# Generate the normal->spike traffic pattern (spike after 2 min, run 6 min):
python run_promo_traffic.py --normal-window 2 --interval 10 --duration 6
```

Full walkthrough — including how to catch it with a Galileo **Signal**, quantify
it with an **Eval**, and block it with a **Luna guardrail** — is in
[`EXPIRED_PROMO_DEMO.md`](./EXPIRED_PROMO_DEMO.md).

## Agent Control (runtime guardrails)

The demo supports **two Agent Control modes**, switchable via the
`AGENT_CONTROL_MODE` env var:

| Mode | When to use | Auth | Where controls live |
|---|---|---|---|
| `enterprise` *(default)* | Demoing against a Galileo cluster with ACE enabled | `GALILEO_API_KEY` via `Galileo-API-Key` header → JWT | Galileo Console, bound to a log stream |
| `oss` | Demoing against a self-hosted Agent Control server (e.g. local Docker) | `AGENT_CONTROL_API_KEY` via SDK default header | Created by `setup_agent_control.py` against the server |

Both modes share the same git-pinned `agent-control-sdk[galileo]` install,
the same `@control()` decorators in `app/agents/action.py`, and the same
two demo controls (`block-zero-refund`, `refund-compliance`). Only the
init kwargs and the control-management flow differ.

To switch:

```bash
# Enterprise (default)
AGENT_CONTROL_MODE=enterprise

# OSS / self-hosted
AGENT_CONTROL_MODE=oss
```

### Enterprise (ACE) mode

1. **Toggle Agent Control on.** Console → Dev Tools → External Flags →
   search "Agent Control" → toggle on. A Controls icon appears in the
   left nav.
2. **Create the demo controls.** Console → Controls → Create New Control.
   Create both:
   - `block-zero-refund` — JSON evaluator on `output`, field constraint
     `amount.min = 0.01`, action `deny`, scope `step_types=["llm"], stages=["post"]`.
   - `refund-compliance` — JSON evaluator on `output`, field constraint
     `amount_matches_receipt.enum = [true]`, action `deny`, scope
     `step_types=["llm"], stages=["post"]`.
3. **Bind both to your log stream.** Open the log stream you'll point
   `GALILEO_LOG_STREAM` at, go to its Controls tab, and "Add" each control.

### Local Galileo SDK pin

The Agent Control → Galileo `ControlSpan` bridge is not yet on PyPI, so
`requirements.txt` installs `galileo` from a local checkout:

```
galileo[openai] @ file:///Users/michaelbranconier/galileo/galileo-python
```

Update that path if your `galileo-python` checkout lives elsewhere. Switch
back to the published `galileo[openai]>=…` once a release ships the bridge.

### Environment variables

ACE replaces the standalone server's `AGENT_CONTROL_API_KEY` /
`AGENT_CONTROL_ADMIN_API_KEY` / `AGENT_CONTROL_SESSION_SECRET` /
`AGENT_CONTROL_DB_URL` with these:

| Var | What it's for |
|---|---|
| `GALILEO_API_KEY` | Galileo API key. Doubles as the AC credential. |
| `GALILEO_API_URL` / `GALILEO_CONSOLE_URL` | Stack URLs. The SDK uses them to resolve project / log stream IDs. |
| `GALILEO_PROJECT` / `GALILEO_LOG_STREAM` | Names of the project + log stream you created above. |
| `AGENT_CONTROL_URL` | ACE public URL on the same stack (e.g. `https://agent-control-<stack>.gcp-dev.galileo.ai`). |
| `AGENT_CONTROL_TARGET_TYPE=log_stream` | ACE binds controls to log streams, not agents. |
| `AGENT_CONTROL_RUNTIME_AUTH_MODE=jwt` | SDK exchanges your API key for a log-stream-scoped JWT per request. |
| `AGENT_CONTROL_API_KEY_HEADER=Galileo-API-Key` | Header the upstream auth shim expects. |
| `AGENT_CONTROL_REFRESH_INTERVAL_SECONDS=5` | How often the SDK polls ACE for control changes. |

Copy `env.example` to `.env`, fill them in, then verify:

```bash
python setup_agent_control.py
```

This does **not** create controls — it only verifies that the SDK can
auth, registers/refreshes the `ai-ops-desk` agent against the resolved
log stream target, and prints the controls bound to that log stream so
you can confirm they made it across from Console.

### How it's wired

- `app/agent_control_setup.py` calls `agent_control.init(target_type="log_stream", target_id=<resolved log_stream_id>, observability_sink_name="registered", api_key_header="Galileo-API-Key", runtime_auth_mode="jwt", …)` on first request.
- `app/agents/action.py` decorates `_create_refund_request_checked` with
  `@control()`. ACE evaluates the output against the bound controls and
  raises `ControlViolationError` on a deny.
- The `galileo` SDK's auto-registered Agent Control bridge converts
  ACE's `ControlExecutionEvent`s into `ControlSpan`s on the active trace.
  Hover the trace in Galileo Console — control evaluations appear inline
  alongside the LLM and tool spans.

Disable the integration entirely with `AGENT_CONTROL_ENABLED=false`.

### OSS (self-hosted) mode

Set `AGENT_CONTROL_MODE=oss` and point `AGENT_CONTROL_URL` at your
standalone Agent Control server. For local dev:

```bash
curl -L https://raw.githubusercontent.com/agentcontrol/agent-control/refs/heads/main/docker-compose.yml \
  | docker compose -f - up -d
```

This brings up Postgres + the AC server + the dashboard at
`http://localhost:8000`. Then in `.env`:

```bash
AGENT_CONTROL_MODE=oss
AGENT_CONTROL_URL=http://localhost:8000
# Optional, only if the server runs with auth enabled:
AGENT_CONTROL_API_KEY=<runtime key>
AGENT_CONTROL_ADMIN_API_KEY=<admin key, used only by setup_agent_control.py>
```

Then create + attach the controls:

```bash
python setup_agent_control.py
```

In OSS mode the script PUTs both controls (`block-zero-refund`,
`refund-compliance`) to `/api/v1/controls`, attaches each to the
`ai-ops-desk` agent, and is idempotent on re-runs. Open the dashboard
at `http://localhost:8000` to toggle controls live.

### Tweak or add controls

Open Galileo Console → Controls to flip controls on/off, edit thresholds,
or add new ones (e.g. block refunds above some max). No code redeploy
needed — the SDK refreshes its cache from ACE every
`AGENT_CONTROL_REFRESH_INTERVAL_SECONDS` (default 5s).

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