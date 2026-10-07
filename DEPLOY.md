# Railway Deployment — AI Ops Desk + Agent Control

Live-demo deployment recipe for the full stack on a **single Railway
project**. The demo supports two Agent Control modes via the
`AGENT_CONTROL_MODE` env var; this doc covers both.

| Mode | Status | Architecture |
|---|---|---|
| **`oss`** | **Active for prod demos right now.** Self-hosted Agent Control server + Postgres on Railway. Controls created via `setup_agent_control.py`. | 4 services |
| **`enterprise`** (ACE) | Planned. Agent Control runs inside the Galileo cluster; controls live in Galileo Console. | 2 services |

You flip between them by changing one Railway env var (`AGENT_CONTROL_MODE`)
plus a few related vars. The application code is identical for both.

## Architecture (OSS mode)

```
                              ┌────────────────────────────────────────┐
                              │  Railway project: ai-ops-desk-demo     │
                              │                                        │
  Browser ── HTTPS ───────────┼─► ai-ops-desk-web        (public)      │
     │                        │       │                                │
     │                        │       └── NEXT_PUBLIC_API_URL ─────────┼──► ai-ops-desk-api (public)
     │                        │                                        │             │
     └── HTTPS ───────────────┼─► agent-control-server   (public)      │             │
                              │       │  (REST API + dashboard UI)    │             │
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

## Generate secrets (OSS mode)

Three new values are needed to turn on Agent Control authentication. What
each one is for:

| Value | Purpose | Set on | Read by |
|---|---|---|---|
| **API key** | Day-to-day credential the SDK presents on every `@control()` call. Lower privilege — cannot create or modify controls. | `agent-control-server` (as `AGENT_CONTROL_API_KEYS`, comma-list); `ai-ops-desk-api` (as `AGENT_CONTROL_API_KEY`). | The Agent Control SDK at runtime, on every outbound request. |
| **Admin key** | High-privilege credential for managing controls and signing into the dashboard. | `agent-control-server` (as `AGENT_CONTROL_ADMIN_API_KEYS`). | The Agent Control dashboard at login; `setup_agent_control.py` (read from your shell when you run it). Never set on a long-running service. |
| **Session secret** | Server-side HMAC key used to sign dashboard login sessions. Without it, every server restart logs everyone out. | `agent-control-server` (as `AGENT_CONTROL_SESSION_SECRET`). | The Agent Control server only. |

You'll also need your existing app secrets: `OPENAI_API_KEY`, `MONGODB_URI`,
`GALILEO_API_KEY`.

```bash
AGENT_CONTROL_API_KEYS=$(uuidgen)
AGENT_CONTROL_ADMIN_API_KEYS=$(uuidgen)
AGENT_CONTROL_SESSION_SECRET=$(openssl rand -hex 32)

cat <<EOF
─── Save these (password manager) ───
AGENT_CONTROL_API_KEYS:        $AGENT_CONTROL_API_KEYS
AGENT_CONTROL_ADMIN_API_KEYS:  $AGENT_CONTROL_ADMIN_API_KEYS
AGENT_CONTROL_SESSION_SECRET:  $AGENT_CONTROL_SESSION_SECRET
──────────────────────────────────────
EOF
```

## Deploy order (OSS mode)

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
# Database connection string. The AC server image ships with psycopg3 only,
# and SQLAlchemy's async engine defaults to psycopg2 for plain postgresql://
# URLs -> ModuleNotFoundError at startup. The +psycopg suffix forces the
# psycopg3 driver. Do NOT reference ${{Postgres.DATABASE_URL}} directly —
# it lacks the suffix.
AGENT_CONTROL_DB_URL=postgresql+psycopg://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}

# Bind to all interfaces so Railway's edge proxy can reach the container.
AGENT_CONTROL_HOST=0.0.0.0
AGENT_CONTROL_PORT=8000

# Enable API key authentication.
AGENT_CONTROL_API_KEY_ENABLED=true
AGENT_CONTROL_API_KEYS=<API key uuid>          # SDK / agent runtime
AGENT_CONTROL_ADMIN_API_KEYS=<admin key uuid>  # dashboard + control mgmt
AGENT_CONTROL_SESSION_SECRET=<session hex>
```

> If `${{Postgres.PGHOST}}` renders literally in the build logs, your
> Postgres service was named in lowercase. Use `${{postgres.PGHOST}}` (or
> whatever case the Railway dashboard shows for the service).

**Smoke test:** open `https://<agent-control-server-domain>.up.railway.app`
in a browser. The dashboard should prompt for an admin API key. Paste the
admin uuid to log in.

### 3. `ai-ops-desk-api`

Existing FastAPI service. Set:

```bash
# Tell the SDK which mode to run in.
AGENT_CONTROL_MODE=oss

# Pin the agent name so a leaked AGENT_CONTROL_AGENT_NAME in any
# build/runtime env can't redirect controls to a different agent.
AGENT_CONTROL_AGENT_NAME=ai-ops-desk

AGENT_CONTROL_URL=https://<agent-control-server-domain>.up.railway.app

# Use the API key, NOT the admin key. This process should never hold an
# admin credential.
AGENT_CONTROL_API_KEY=<API key uuid (matches agent-control-server's AGENT_CONTROL_API_KEYS)>

# How often the SDK polls for control changes. SDK default is 60s; we use
# 5s so toggling a control in the dashboard takes effect quickly.
AGENT_CONTROL_REFRESH_INTERVAL_SECONDS=5

# Galileo logging (these were already set; listed for completeness).
GALILEO_API_KEY=<your galileo api key>
GALILEO_PROJECT=ai_ops_desk
GALILEO_LOG_STREAM=dev-1
GALILEO_CONSOLE_URL=https://console.dev.galileo.ai
GALILEO_API_URL=https://api.dev.galileo.ai

# CORS allowlist for the frontend. Add to the existing comma-separated list.
ALLOWED_ORIGINS=https://<ai-ops-desk-web-domain>.up.railway.app
```

**Register the agent and create the controls (one-time).** Run from your
laptop against the prod AC server:

```bash
cd mongodb_local_nyc_demo/ai-ops-desk

AGENT_CONTROL_MODE=oss \
AGENT_CONTROL_URL=https://<agent-control-server-domain>.up.railway.app \
AGENT_CONTROL_ADMIN_API_KEY=<admin key uuid> \
  .venv/bin/python setup_agent_control.py
```

The script creates and attaches both `block-zero-refund` and
`refund-compliance` to the `ai-ops-desk` agent on the prod server. It is
idempotent — re-run any time you change the control definition in source.

> **Optional:** wire `setup_agent_control.py` as a Railway pre-deploy /
> release command on `ai-ops-desk-api` to reconcile the control state on
> every deploy.

### 4. `ai-ops-desk-web`

Existing Next.js service.

```bash
NEXT_PUBLIC_API_URL=https://<ai-ops-desk-api-domain>.up.railway.app
```

`NEXT_PUBLIC_*` variables are inlined at build time. Trigger a redeploy
after changing this value.

## Post-deploy smoke test (OSS)

1. Open `https://<agent-control-server-domain>.up.railway.app` and log in
   with the admin key.
2. Confirm the `ai-ops-desk` agent exists with both `block-zero-refund` and
   `refund-compliance` attached and `enabled: true`.
3. Open `https://<ai-ops-desk-web-domain>.up.railway.app` and run the
   `refund_headphones` scenario for `user_001`.
4. Open the Ops drawer (top-left 👁 button). The `_create_refund_request`
   row should show amber 🛡 with
   `Blocked by Agent Control · control: refund-compliance`.
5. In the AC dashboard, toggle the control's `enabled` to `false`. Wait
   ~5 seconds (matches `AGENT_CONTROL_REFRESH_INTERVAL_SECONDS`), then
   re-run the scenario. The block goes away. Toggle back on and re-run;
   the block returns.

Step 5 demonstrates runtime control of agent behavior without redeploying.

---

## Switching to ACE later (when ready)

When the Galileo Agent Control Enterprise path is ready for live demos,
flipping production to ACE is a Railway env var change. **No code change
or redeploy needed beyond restarting the service** — `agent_control.init()`
reads the mode at process start.

### What changes

1. On `ai-ops-desk-api`, set:

   ```bash
   AGENT_CONTROL_MODE=enterprise

   # Point at the ACE endpoint on your Galileo stack.
   AGENT_CONTROL_URL=https://agent-control.<stack>.galileo.ai

   # ACE-only knobs.
   AGENT_CONTROL_TARGET_TYPE=log_stream
   AGENT_CONTROL_RUNTIME_AUTH_MODE=jwt
   AGENT_CONTROL_API_KEY_HEADER=Galileo-API-Key

   # Remove (unset in Railway) — these only apply to OSS mode:
   #   AGENT_CONTROL_API_KEY
   #   AGENT_CONTROL_ADMIN_API_KEY
   ```

2. In Galileo Console:
   - Dev Tools → External Flags → toggle Agent Control on.
   - Controls → create `block-zero-refund` and `refund-compliance` (same
     definitions as the OSS catalog in `setup_agent_control.py`).
   - Open the log stream pointed at by `GALILEO_LOG_STREAM` → Controls
     tab → "Add" both controls.

3. (Optional) Decommission the OSS Railway services once ACE is verified
   in prod. Until then, keep `postgres` + `agent-control-server` running
   so you can flip back instantly if ACE hits an issue mid-demo.

### Verifying the flip

```bash
cd mongodb_local_nyc_demo/ai-ops-desk

# Run the verifier against ACE (mode=enterprise, default).
.venv/bin/python setup_agent_control.py
```

Expected:

```
Mode:                 enterprise (ACE)
✓ Resolved project_id=… log_stream_id=…
✓ AC server healthy: healthy
✓ Found agent 'ai-ops-desk' on ACE
Controls bound to log_stream:…:
  - block-zero-refund (enabled=True)
  - refund-compliance (enabled=True)
```

---

## Common pitfalls

- **Postgres URL scheme — must include `+psycopg`.** AC server image ships
  with psycopg3 only; SQLAlchemy defaults to psycopg2 for plain
  `postgresql://` and crashes with `ModuleNotFoundError: No module named
  'psycopg2'`. Always use `postgresql+psycopg://`.

- **Confusing the API key with the admin key.** Runtime `@control()` calls
  succeed but `setup_agent_control.py` returns 401/403. The API key belongs
  on `ai-ops-desk-api` as `AGENT_CONTROL_API_KEY`. The admin key only goes
  in the shell when running the setup script — never as a long-lived var
  on any service.

- **Leaked `AGENT_CONTROL_AGENT_NAME`.** The Cursor IDE's AC hook sets this
  to `cursor-agent` in your laptop shell. The SDK reads the env var, so a
  leak silently registers controls under the wrong agent and your blocks
  never fire. Pin `AGENT_CONTROL_AGENT_NAME=ai-ops-desk` in `.env` (local)
  and Railway (prod). On laptop, `unset AGENT_CONTROL_AGENT_NAME` if you've
  used the hook recently.

- **`AGENT_CONTROL_URL` missing the scheme (ACE).** ACE 401s with
  `Request URL is missing an 'http://' or 'https://' protocol.` if you
  paste just the host. Always include `https://`.

- **Inconsistent image tag between environments.** If local runs on `7.7.0`
  and Railway runs on `7.5.0`, behavior may diverge. Bump the tag in both
  places in the same change.
