# Railway Deployment — AI Ops Desk

Live-demo deployment recipe for the full stack on a **single Railway
project**. Two services total, both public over HTTPS.

> **Migrated from standalone Agent Control to Agent Control Enterprise.**
> This repo previously hosted a `postgres` + `agent-control-server` pair
> on Railway. We've moved to **Agent Control Enterprise (ACE)**, which
> runs inside the Galileo cluster you point `GALILEO_API_URL` at. Delete
> those two Railway services if they still exist; only `ai-ops-desk-api`
> and `ai-ops-desk-web` remain.

## Architecture

```
                          ┌──────────────────────────────────────────┐
                          │  Railway project: ai-ops-desk-demo       │
                          │                                          │
  Browser ── HTTPS ───────┼─► ai-ops-desk-web      (public)          │
     │                    │      │                                   │
     │                    │      └── NEXT_PUBLIC_API_URL ─► ai-ops-desk-api (public)
     │                    │                                          │
     └── HTTPS to Galileo ┼──► console.<stack>.galileo.ai             │
                          │      api.<stack>.galileo.ai               │
                          │      agent-control.<stack>.galileo.ai     │
                          └──────────────────────────────────────────┘

  MongoDB stays on Atlas. Agent Control runs inside the Galileo cluster.
```

## One-time prep

1. **Galileo Console:** Dev Tools → toggle Agent Control on. Create the
   `block-zero-refund` and `refund-compliance` controls. Open your log
   stream → Controls → "Add" both. (See [`ai-ops-desk/README.md`](ai-ops-desk/README.md)
   for control field details.)
2. **Galileo API key:** generate one with access to that project.
3. **Galileo SDK pin (prod-only caveat):** `requirements.txt` installs
   `galileo` from a local path because the Galileo→AC bridge isn't on
   PyPI yet. Railway can't reach your laptop, so before deploying either:
   - point `requirements.txt` at a published `galileo` git tag that
     includes the bridge: `galileo[openai] @ git+https://github.com/rungalileo/galileo-python.git@<tag>`, or
   - vendor `galileo-python` into this repo (submodule or copy) and use
     `galileo[openai] @ file://./vendor/galileo-python`.

## Deploy

### 1. `ai-ops-desk-api`

Existing FastAPI service. Set the following variables (Galileo + ACE):

```bash
# Galileo
GALILEO_API_KEY=<your-galileo-api-key>
GALILEO_CONSOLE_URL=https://console-<stack>.gcp-dev.galileo.ai
GALILEO_API_URL=https://api-<stack>.gcp-dev.galileo.ai
GALILEO_PROJECT=<project name created in Console>
GALILEO_LOG_STREAM=<log stream name created in Console>

# Agent Control Enterprise
AGENT_CONTROL_URL=https://agent-control-<stack>.gcp-dev.galileo.ai
AGENT_CONTROL_TARGET_TYPE=log_stream
AGENT_CONTROL_RUNTIME_AUTH_MODE=jwt
AGENT_CONTROL_API_KEY_HEADER=Galileo-API-Key
AGENT_CONTROL_REFRESH_INTERVAL_SECONDS=5

# App
OPENAI_API_KEY=<your-openai-api-key>
MONGODB_URI=<your-atlas-uri>
ALLOWED_ORIGINS=https://<ai-ops-desk-web-domain>.up.railway.app
```

`GALILEO_API_KEY` doubles as the Agent Control credential — no separate
`AGENT_CONTROL_API_KEY` is needed.

**Verify wiring (one-time, from your laptop):**

```bash
cd mongodb_local_nyc_demo/ai-ops-desk
python setup_agent_control.py
```

This does not create controls. It registers/refreshes the `ai-ops-desk`
agent against the resolved log stream and lists the controls bound to it.

### 2. `ai-ops-desk-web`

Existing Next.js service.

```bash
NEXT_PUBLIC_API_URL=https://<ai-ops-desk-api-domain>.up.railway.app
```

`NEXT_PUBLIC_*` variables are inlined at build time. Trigger a redeploy
after changing this value.

## Post-deploy smoke test

1. Open `https://<ai-ops-desk-web-domain>.up.railway.app` and run the
   `refund_headphones` scenario for `user_001`.
2. Open the Ops drawer (top-left 👁 button). The `_create_refund_request`
   row should show amber 🛡 with `Blocked by Agent Control · control: refund-compliance`.
3. In Galileo Console → your trace, confirm `type=control` spans appear
   inline with the LLM/tool spans.
4. In Galileo Console → Controls → `refund-compliance`, toggle `enabled`
   off. Wait `AGENT_CONTROL_REFRESH_INTERVAL_SECONDS` (default 5s), rerun
   the scenario — the receipt now succeeds (and is incorrect, by design).
   Toggle back on; the block returns.

Step 4 demonstrates runtime control of agent behavior without redeploying.

## Common pitfalls

- **`AGENT_CONTROL_URL` missing the scheme.** ACE 401s with
  `Request URL is missing an 'http://' or 'https://' protocol.` if you
  paste just the host. Always include `https://`.
- **Wrong stack URLs.** `GALILEO_API_URL`, `GALILEO_CONSOLE_URL`, and
  `AGENT_CONTROL_URL` must all point at the same Galileo stack. Mixing
  stacks produces silent 401s on JWT exchange.
- **Log stream not bound.** If `setup_agent_control.py` reports zero
  controls, the controls were created in Console but never attached to
  the log stream's Controls tab. Add them there.
- **Local `galileo-python` path leaked into prod.** `requirements.txt`
  uses `file:///Users/...` for fast iteration. Replace with a git tag or
  vendored copy before deploying — pip install will fail in CI/Railway
  otherwise.
- **Leaked `AGENT_CONTROL_AGENT_NAME` in the shell.** The demo defaults
  to `ai-ops-desk`, but if a developer machine has this set globally
  (e.g. for the Cursor IDE hook) the SDK will register under the wrong
  agent. Avoid setting it as a shell-level default.
