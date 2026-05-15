# Railway Deployment — AI Ops Desk + Agent Control

Live-demo deployment recipe for the full stack on a **single Railway
project**. Four services total, every service public over HTTPS, auth keys
enforced at the application layer.

## Architecture

```
                              ┌────────────────────────────────────────┐
                              │  Railway project: ai-ops-desk-demo     │
                              │                                        │
  Browser ── HTTPS ───────────┼─► ai-ops-desk-web        (public)      │
     │                        │       │                                │
     │                        │       └── NEXT_PUBLIC_API_URL ─────────┼──► ai-ops-desk-api (public)
     │                        │                                        │             │
     └── HTTPS ───────────────┼─► agent-control-server   (public)      │             │
                              │       │  (serves both the REST API    │             │
                              │       │   and the dashboard UI)       │             │
                              │       │                                │             │
                              │  postgres (managed, no public domain) │             │
                              │       ▲                                │             │
                              │       └─ consumed by agent-control-server            │
                              └────────────────────────────────────────┘
                                                                                    │
  MongoDB stays on Atlas (existing). Not deployed to Railway. ◄─────────────────────┘
```

Every service except Postgres has a public Railway domain. Inter-service
traffic is authenticated with API keys, not network isolation.

The Agent Control server image bundles its dashboard UI — both are served
from a single container on a single port. No separate UI service is
required.

## Image pin

Pin the Agent Control server image. Do not use `:latest`.

```
galileoai/agent-control-server:7.7.0
```

When upgrading: bump the tag locally, smoke-test, then bump the same tag in
Railway and in `mongodb_local_nyc_demo/ai-ops-desk/env.example`.

## Generate secrets

Three new values are needed to turn on Agent Control authentication. What
each one is for:

| Value | Purpose | Set on | Read by |
|---|---|---|---|
| **API key** | Day-to-day credential the SDK presents on every `@control()` call and observability event. Lower privilege — cannot create or modify controls. | `agent-control-server` (as `AGENT_CONTROL_API_KEYS`, comma-list); `ai-ops-desk-api` (as `AGENT_CONTROL_API_KEY`, single value). | The Agent Control SDK at runtime, on every outbound request, as the `X-API-Key` header. |
| **Admin key** | High-privilege credential for managing controls (create, update, attach, delete) and signing into the dashboard. | `agent-control-server` (as `AGENT_CONTROL_ADMIN_API_KEYS`, comma-list). | The Agent Control dashboard (entered at login); the `setup_agent_control.py` script (read from your shell env when you run it). Never set on a long-running service. |
| **Session secret** | Server-side HMAC key used to sign dashboard login sessions. Without it, every server restart logs everyone out. | `agent-control-server` (as `AGENT_CONTROL_SESSION_SECRET`). | The Agent Control server only. Never sent to the client. |

You'll also need your existing app secrets: `OPENAI_API_KEY`, `MONGODB_URI`,
`GALILEO_API_KEY`.

Generate the three new values, export them for this shell, and print them
in a copy-pasteable block:

```bash
AGENT_CONTROL_API_KEYS=$(uuidgen)
AGENT_CONTROL_ADMIN_API_KEYS=$(uuidgen)
AGENT_CONTROL_SESSION_SECRET=$(openssl rand -hex 32)

cat <<EOF
─── Save these values (password manager) ───
AGENT_CONTROL_API_KEYS:        $AGENT_CONTROL_API_KEYS
AGENT_CONTROL_ADMIN_API_KEYS:  $AGENT_CONTROL_ADMIN_API_KEYS
AGENT_CONTROL_SESSION_SECRET:  $AGENT_CONTROL_SESSION_SECRET
─────────────────────────────────────────────
EOF
```

## Deploy order

Deploy services in the order below.

### 1. `postgres`

Railway → **+ New** → **Database** → **Add PostgreSQL**.

Railway provisions Postgres and exposes `PGUSER`, `PGPASSWORD`, `PGDATABASE`,
`PGPORT`, `PGHOST` as reference variables. No public domain, no further
config.

### 2. `agent-control-server`

**+ New** → **Empty Service** → name it `agent-control-server`.

**Settings → Source → Docker Image:**
```
galileoai/agent-control-server:7.7.0
```

**Settings → Networking:** enable a public domain. Save the assigned URL
(e.g. `agent-control-server-production.up.railway.app`); steps 3 and 4 both
need it.

**Variables:**

```bash
# Database connection string. The Agent Control server's image ships with
# psycopg3 (NOT psycopg2), and uses SQLAlchemy's async engine. Plain
# postgresql:// makes SQLAlchemy default to psycopg2 -> ModuleNotFoundError
# at startup. You MUST use the +psycopg suffix to force the psycopg3 driver.
# Don't reference ${{Postgres.DATABASE_URL}} directly — it lacks the suffix.
AGENT_CONTROL_DB_URL=postgresql+psycopg://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}

# Bind to all interfaces so Railway's edge proxy can reach the container.
AGENT_CONTROL_HOST=0.0.0.0
AGENT_CONTROL_PORT=8000

# Enable API key authentication.
AGENT_CONTROL_API_KEY_ENABLED=true
AGENT_CONTROL_API_KEYS=<API key uuid>        # SDK / agent runtime
AGENT_CONTROL_ADMIN_API_KEYS=<admin key uuid> # dashboard login + control management
AGENT_CONTROL_SESSION_SECRET=<session hex>
```

> If `${{Postgres.PGHOST}}` renders literally in the build logs, your
> Postgres service was named in lowercase. Use `${{postgres.PGHOST}}` (or
> whatever case the Railway dashboard shows for the service).

**Smoke test:** open `https://<agent-control-server-domain>.up.railway.app`
in a browser. The dashboard should prompt for an admin API key. Paste the
admin uuid to log in.

### 3. `ai-ops-desk-api`

Existing FastAPI service. Add the following variables:

```bash
AGENT_CONTROL_URL=https://<agent-control-server-domain>.up.railway.app

# Use the API key, NOT the admin key. This process should never hold an
# admin credential.
AGENT_CONTROL_API_KEY=<API key uuid (same value as agent-control-server's AGENT_CONTROL_API_KEYS)>

# How often the SDK polls for control changes. Default in the SDK is 60s;
# we use 5s so toggling a control in the dashboard takes effect quickly
# during the demo.
AGENT_CONTROL_REFRESH_INTERVAL_SECONDS=5

# CORS allowlist for the frontend. If ALLOWED_ORIGINS already has values,
# add this one to the comma-separated list.
ALLOWED_ORIGINS=https://<ai-ops-desk-web-domain>.up.railway.app
```

**Register the agent and control on the new server (one-time).** Run from
your laptop:

```bash
cd mongodb_local_nyc_demo/ai-ops-desk

AGENT_CONTROL_URL=https://<agent-control-server-domain>.up.railway.app \
AGENT_CONTROL_ADMIN_API_KEY=<admin key uuid> \
  python setup_agent_control.py
```

The script is idempotent — re-run it any time you change the control
definition in source.

> **Optional:** wire `setup_agent_control.py` as a Railway pre-deploy or
> release command on `ai-ops-desk-api` to reconcile the control state on
> every deploy. Recommended only if you change controls frequently.

### 4. `ai-ops-desk-web`

Existing Next.js service.

```bash
NEXT_PUBLIC_API_URL=https://<ai-ops-desk-api-domain>.up.railway.app
```

`NEXT_PUBLIC_*` variables are inlined at build time. Trigger a redeploy
after changing this value.

## Post-deploy smoke test

1. Open `https://<agent-control-server-domain>.up.railway.app` and log in
   with the admin key.
2. Confirm the `ai-ops-desk` agent exists with `block-zero-refund` attached
   and `enabled: true`.
3. Open `https://<ai-ops-desk-web-domain>.up.railway.app` and run the
   `refund_bluetooth_earbuds` scenario for `user_001`.
4. Open the Ops drawer (top-left 👁 button). The `_create_refund_request`
   row should show amber 🛡 with
   `Blocked by Agent Control · control: block-zero-refund`.
5. In the Agent Control dashboard, toggle the control's `enabled` to
   `false`. Wait for the SDK to pick up the change (5 seconds with the
   demo's `AGENT_CONTROL_REFRESH_INTERVAL_SECONDS=5`), then re-run the
   scenario. The receipt now shows ✓ 201 with `amount: 0`. Toggle back on
   and re-run; the block returns.

Step 5 demonstrates runtime control of agent behavior without redeploying.

## Common pitfalls

- **Postgres URL scheme — must include `+psycopg`.** The AC server image
  ships with psycopg3 only, but SQLAlchemy's default for `postgresql://` is
  psycopg2. Booting with the plain scheme (including Railway's stock
  `DATABASE_URL`) crashes with `ModuleNotFoundError: No module named
  'psycopg2'`. Always set `AGENT_CONTROL_DB_URL` to
  `postgresql+psycopg://...` built from the
  individual `PG*` reference variables with the `postgresql+psycopg://`
  prefix, as shown in step 2.

- **Confusing the API key with the admin key.** Runtime `@control()` calls
  succeed but `setup_agent_control.py` returns `401` or `403`. The API key
  belongs in `AGENT_CONTROL_API_KEY` on `ai-ops-desk-api`. The admin key
  belongs only in the shell environment when running the setup script —
  never as a long-lived variable on any service.

- **Inconsistent image tag between environments.** If local runs on
  `7.7.0` and Railway runs on `7.5.0`, behavior may diverge. When bumping,
  update the tag in `mongodb_local_nyc_demo/ai-ops-desk/env.example` and
  the Railway service in the same change.

- **Leaked `AGENT_CONTROL_AGENT_NAME` in the shell.** The demo hard-codes
  its agent name to `ai-ops-desk`, but the Agent Control SDK and some
  external integrations (e.g. the Cursor IDE hook) read
  `AGENT_CONTROL_AGENT_NAME` from the environment. If this variable is set
  globally on a developer machine, those integrations may register
  controls against the wrong agent. Avoid setting it as a shell-level
  default.
