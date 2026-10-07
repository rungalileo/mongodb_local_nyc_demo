# Voltway — AI Ops Desk

A customer-support agent for Voltway, a fictional online retailer, built to show
Splunk Agent Observability and Agent Control working against a real LangGraph
agent and a real MongoDB Atlas database.

**The demo is the expired promo.** The agent reads a stale promo cache, proposes
a discount that has already expired, and an LLM-as-judge eval catches it.
Walkthrough: [`ai-ops-desk/EXPIRED_PROMO_DEMO.md`](ai-ops-desk/EXPIRED_PROMO_DEMO.md).

**Integration costs is setup, not a demo.** It backfills evaluator traffic so
that the Console's cost view shows, across several weeks of history, what
LLM-as-judge evaluators cost compared with Luna-based judges — the kind of
long-run comparison you can point at but could never produce live. Run it ahead
of time and the graph is simply there when you need it:
[`ai-ops-desk/integration-cost-demo/README.md`](ai-ops-desk/integration-cost-demo/README.md).
Budget a few minutes for the run, and don't do it in front of an audience — the
chart is unreliable until the job finishes.

Two processes: a FastAPI backend on **8000** and a Next.js frontend on **3000**.

> A naming note: the environment variables, the Python SDK and the on-disk state
> file are all still named `GALILEO_*` / `galileo`. That is the underlying SDK,
> not a separate product — leave those identifiers exactly as they are.

---

## What you need before you start

| | Why |
|---|---|
| Python 3.12 and Node 20+ | Backend is FastAPI, frontend is Next 16 / React 19 |
| A **MongoDB Atlas** cluster | Must be Atlas, not self-hosted — the refund-policy path uses `$vectorSearch`, which only Atlas provides |
| An OpenAI API key | Runs the agent itself |
| A **Splunk Agent Observability API key for the stack you point at** | Keys are per-stack. A key from a different instance returns `401 Invalid credentials`, which is the single most common setup failure |

This repo is configured against the Splunk Agent Observability demo stack
(`demo.sao.splunkcloud.com`). Issue your key from that Console, not another one.

---

## Setup

### 1. Clone and install

The default branch is `main`, but the demo lives on
`promo-hallucination-clarity` — check it out or nothing below will match:

```bash
git clone git@github.com:rungalileo/mongodb_local_nyc_demo.git
cd mongodb_local_nyc_demo
git checkout promo-hallucination-clarity

# Backend
cd ai-ops-desk
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Frontend
cd ../ai-ops-desk-web
npm install
```

### 2. Configure the backend

```bash
cd ../ai-ops-desk
cp env.example .env
```

`.env` is gitignored, so your keys stay out of git. Never commit it, and never
paste a key into a tracked file — treat anything in the repo as public.

Fill in the four values that are yours:

```bash
MONGODB_URI="<your Atlas SRV string, from Atlas → Connect → Drivers>"
OPENAI_API_KEY="<your OpenAI key>"
GALILEO_API_KEY="<your key from the Splunk Agent Observability Console>"
GALILEO_PROJECT="<see "Choosing your project" below>"
```

Leave these as they are — they point at the demo stack and are not secrets:

```bash
MONGODB_DATABASE=ai_ops_desk
AGENT_CONTROL_MODE="enterprise"
GALILEO_CONSOLE_URL="https://console.demo.sao.splunkcloud.com"
GALILEO_API_URL="https://api.demo.sao.splunkcloud.com"
GALILEO_LOG_STREAM="Default"
```

`env.example` documents every remaining variable inline, including the
`AGENT_CONTROL_*` block. In enterprise mode your `GALILEO_API_KEY` doubles as
the Agent Control credential, so there is no second key to obtain. If you don't
need the steer control, set `AGENT_CONTROL_ENABLED="false"` and skip that
section entirely — everything else still works.

Two more things while you're in Atlas:

- **Allowlist your IP** under Network Access, or every query silently returns
  nothing and the user list shows up empty.
- That same API key is what the integration-cost setup uses to change a model's
  price **org-wide**, which affects every project on that model, not just yours.
  If you share a stack with colleagues, read
  [`ai-ops-desk/integration-cost-demo/README.md`](ai-ops-desk/integration-cost-demo/README.md)
  before pressing those buttons.

### 3. Seed the database

Only needed for a fresh database. Run from `ai-ops-desk/` with `.env` filled in:

```bash
.venv/bin/python setup_products.py && .venv/bin/python setup_promos.py
.venv/bin/python setup_orders.py && .venv/bin/python setup_refund_requests.py
.venv/bin/python setup_tickets.py
.venv/bin/python setup_policies.py       # writes embeddings — see note
```

`setup_policies.py` needs an Atlas vector search index that you create by hand
in the Atlas UI, because the driver cannot create one:

- Index name `policy_vectors`, field `embedding`, **1536** dimensions

Without it the refund-policy lookup retrieves nothing. The script tells you so
at the end rather than failing silently.

### 4. Run it

Two terminals.

```bash
# Terminal 1 — backend
cd ai-ops-desk && .venv/bin/uvicorn app.api:app --reload --port 8000
```

```bash
# Terminal 2 — frontend
cd ai-ops-desk-web && npm run dev
```

Open <http://localhost:3000>. Keep the backend on port 8000 — the frontend
defaults to `http://localhost:8000` outside production and only looks elsewhere
if you set `NEXT_PUBLIC_API_URL`.

Sanity check: `curl localhost:8000/api/health` should return `{"ok":true}`.

---

## Choosing your project and log stream

This is the part worth reading carefully, because the app can take its target
from two places and one of them wins.

### First run: create it from the UI

You don't have to create anything in the Console by hand. Open the **Ops
drawer** in the app and use **Generate demo traffic**:

1. Type a **Project name** (e.g. `my-voltway`) and leave **Log stream name** as
   `Default`.
2. Run it.

That creates the project and log stream, enables the demo evals, attaches
the `promo-proposal-steer` control (disabled), injects a few weeks of promo
conversations, and repoints live chat at the new project.

One gotcha: the **Live target** section's "Point live traces here" button does
**not** create anything — it resolves the names and refuses if they don't exist.
Use it to switch between projects you already have, not to make a new one.

### Making it stick: yes, the env var works — after you clear the pin

Your instinct is right, with one catch. When you point the app at a project from
the UI, that choice is written to a state file:

```
ai-ops-desk/.galileo_active_target.json
```

On every startup the backend reads that file and re-applies it, **overriding
`GALILEO_PROJECT` from `.env`**. From `restore_active_target()` in
`app/promo_demo_provision.py`:

```python
"""Re-apply a previously provisioned live target on process startup.

Call this AFTER ``load_dotenv`` so it takes precedence over the .env
defaults. ...
"""
```

So the precedence is:

1. `.galileo_active_target.json` — the UI pin, if it exists
2. `GALILEO_PROJECT` / `GALILEO_LOG_STREAM` in `.env` — the default otherwise

To make your project the permanent default, do both halves:

```bash
# 1. Set the default in .env
GALILEO_PROJECT="my-voltway"
GALILEO_LOG_STREAM="Default"

# 2. Remove the pin that would otherwise override it
rm ai-ops-desk/.galileo_active_target.json

# 3. Restart the backend
```

Or click **Revert to default** in the Live target section, which deletes the pin
for you.

**Restart after editing `.env`, before using "Revert to default".** The default
is captured once at import, so if you edit `.env` and click Revert without
restarting, it reverts to the *old* value and looks like your edit was ignored:

```python
# app/promo_demo_provision.py — read once, at import
_ENV_DEFAULT_PROJECT = os.environ.get("GALILEO_PROJECT")
_ENV_DEFAULT_LOG_STREAM = os.environ.get("GALILEO_LOG_STREAM") or "Default"
```

Self-healing is built in one direction: if the pinned project gets deleted in the
Console, the app clears the pin on the next startup and falls back to your `.env`
default rather than writing traces into a dead target.

### Confirming it took

In the Live target section, **Run test (write · verify · cleanup)** writes a
marker trace, confirms it landed in the stream you expect, probes Agent Control,
and deletes the marker. Use it after any repoint — it's faster than chatting and
hunting for the trace in the Console.

---

## When something doesn't work

| Symptom | Cause |
|---|---|
| `401 Invalid credentials` | Key issued for a different stack than `GALILEO_API_URL` |
| Empty user list, no errors | Your IP isn't allowlisted in Atlas, or `MONGODB_URI` lost its quotes |
| `Unable to generate response due to API error` | Corporate TLS interception breaking the OpenAI call |
| Refund answers cite no policy | `policy_vectors` index missing, or `setup_policies.py` never ran |
| Traces land in the wrong project | A stale `.galileo_active_target.json` — see above |

More detail lives in [`ai-ops-desk/README.md`](ai-ops-desk/README.md), which
covers the agent internals, the failure toggles, and the CLI scenario runner.

---

## Repo layout

```
ai-ops-desk/            FastAPI backend, LangGraph agent, seed scripts
  app/                  API, agent, observability + Agent Control wiring
  integration-cost-demo/ Cost-view setup and its trace injector
ai-ops-desk-web/        Next.js frontend (chat UI + Ops drawer)
DEPLOY.md               Railway deployment notes
```

Kubernetes manifests, ingress Basic Auth, and the o11y-field-demos runbook live
on the `k8s-deployment` branch, not here.
