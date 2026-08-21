# Expired-Promo Use Case

This demo adds a self-contained failure mode to the AI Ops Desk: the agent
honors a **discount whose promo has already expired**, then quantifies and
blocks that behavior with Galileo.

The story arc mirrors the existing refund-compliance demo:

1. **Observe** the failure in a trace.
2. **Signal** — flag every run where an expired promo was applied.
3. **Eval** — turn the signal into a metric so you can measure how often it
   happens and chart the leaked discount over time.
4. **Guardrail** — add a Luna-backed guardrail that blocks the apply when the
   promo is expired.

---

## The narrative

A customer shops for an expensive catalog item (an iPhone 16 Pro Max, a pro
laptop, …). The web chat runs a **two-turn** flow:

**Turn 1 — the customer asks:**

> "Give me the best discounts on the YPhone 16 Pro Max from the past 6 months"

Asking for the *best historical* deals is what leads the agent to surface an old
offer in the first place — the failure is that it then treats that lapsed deal as
if it were still applicable and offers to apply it.

The agent:

1. Classifies the intent as `promo_inquiry`.
2. Calls **`check_promotions`**, which returns the **full, honest** promo list —
   every candidate with its `effective_until` end date. The tool also computes an
   `expired` flag for each (used by the trace signals + guardrail). Both the
   expired `QMOBILE` ($700 off) and the live `FALL-SALE` ($200 off) come back. End
   dates are anchored to *today* (live ≈ +30d, stale ≈ −7d) so the split holds on
   any demo day.
3. Runs the **`Select Promotion`** LLM step (temperature 0). The prompt lists each
   promo's **end date but no pre-computed expiry verdict and no "today's date"**,
   and tells the model only to offer the **largest discount**. It greedily picks
   the biggest — the **expired** `QMOBILE` — because it never does the "is this
   date in the past?" check. That's the reasoning failure (an LLM choice, not a
   Python `max()`, and not a hint we spoon-fed it). It's stashed as the "promo in
   focus" and proposed:
   *"Voltway is running the QMobile promotion, saving you 70% off ($700) … This
   offer is listed with an end date of Jun 6, 2026. Want me to apply it?"* — the
   agent
   **states the (already-lapsed) end date plainly**, the surface-level tell.

**Turn 2 — the customer says "yes":**

4. The affirmation plus the pending promo routes straight to **`apply_discount`**,
   which applies that exact expired promo, adds the item to the cart, and
   confidently confirms the savings with a **discount receipt card** (list price
   → −discount → new price).

The agent never reasons that the promo expired even though it recited the date.
That gap — a cheerful "you saved $700!" reply, an end date sitting in the chat,
and an expired-promo signal in the trace — is the whole point.

> **With the steer control on** (see below), the `Select Promotion` step is
> intercepted: the model's expired `QMOBILE` pick is caught, the agent re-runs
> the selection over **live offers only**, and proposes the valid `FALL-SALE`
> (−$200) instead — or tells the customer there's no active promo if none are
> live.

### Where the failure lives (surface + technical)

- **Technical:** `check_promotions` hands over correct, complete data (end dates,
  plus a code-computed `expired` flag for the trace/guardrail). The **`Select
  Promotion` LLM step** only gets the end dates (no pre-labeled expiry, no today's
  date) and, told to maximize savings, chooses the expired promo — it never
  reasons about temporal validity. A genuine model reasoning failure the guardrail
  can steer. (`get_promos_for_sku` still returns all promos unfiltered; the *tool*
  isn't the failure, the *choice* is. The deterministic date check lives in the
  guardrail, which is exactly the capability the LLM lacks.)
- **Surface:** the propose reply recites the promo's end date as a normal detail
  (`synthesizer._render_promo_propose_reply`), so a date that has actually
  lapsed is visible in the chat itself.
- `apply_discount` applies whatever was selected and emits `promo_expired: true`.

> **Two-turn (UI) vs single-turn (CLI / traffic generator).** The web chat is
> two-turn: propose, then apply on "yes" (the pending promo is remembered per
> chat session in `app/session_cache.py`). If a message asks to apply in the same
> breath ("…and add it to my cart"), the agent does both at once. The scripted
> CLI and the traffic generator have **no chat session**, so they always take the
> single-turn path and fall back to the time-based **spike** schedule
> (`app/promo_spike.py`) rather than a session-remembered offer.

---

## The "spike" pattern (discount as metadata)

`apply_discount` logs the applied dollar amount as **span metadata** on the
`Apply Discount` tool span:

| metadata key    | example        | meaning |
|-----------------|----------------|---------|
| `discount_usd`  | `"599.50"`     | dollars taken off (the value to chart) |
| `list_price`    | `"1199.00"`    | catalog price before discount |
| `promo_code`    | `"SPRING-SAVER"` | which promo was applied |
| `promo_expired` | `"true"`       | always true in this demo |
| `promo_end_date`| ISO timestamp  | when the promo actually ended (past) |
| `discount_tier` | `"normal"` / `"spike"` | which schedule tier produced it |

The magnitude follows a **time schedule** (`app/promo_spike.py`) anchored to
when the traffic run started:

- **Normal window** (first `PROMO_NORMAL_WINDOW_SECONDS`, default 10 min): small
  seasonal discounts, ~$5–$60 (`SPRING-SAVER`).
- **Spike window** (after that): clearance blowout, 40–55% of list price
  (`CLEARANCE-BLOWOUT`).

Plot `discount_usd` over time in the trace view and you get a flat line that
suddenly jumps — a textbook anomaly for the demo.

> **Where do I actually see the `$` in the Console?** Two places:
>
> 1. **Inside a trace (span detail):** it's on the nested **`Apply Discount`**
>    tool span. Open a trace → expand the **Apply Discount** span → **Metadata**
>    → `discount_usd`, `promo_expired`, `promo_code`, etc.
> 2. **As a column in the trace table:** the column selector only surfaces
>    **trace-level** metadata (that's why token count shows — it's a native
>    metric, not span metadata). So the runner also copies the applied-discount
>    fields onto the **trace root** (`user_metadata`): `discount_usd`,
>    `promo_expired`, `promo_code`, `promo_end_date`, `apply_status`, and
>    `attempted_discount_usd` (when blocked). Click the **columns icon above the
>    trace table** and enable `discount_usd` / `promo_expired` to show them as
>    columns (comma-free string values, so they sort/filter as numbers).
>
> Sessions created before this feature won't have it — generate fresh traffic,
> or use the injector below (which sets the same trace-level metadata).

---

## Files

Added:
- `app/models/product.py` — shoppable catalog item.
- `app/models/promo.py` — time-boxed discount (`is_expired()` helper).
- `app/promo_spike.py` — the normal→spike discount schedule.
- `setup_products.py` — seeds the catalog (4 expensive items).
- `setup_promos.py` — seeds promos per SKU: 1 live (`STUDENT-SAVE`, −$100) +
  2 expired tiers (`SPRING-SAVER`, `CLEARANCE-BLOWOUT` ~50%).
- `app/promo_demo_provision.py` — one-click provisioning for a fresh project
  (project + log stream + LLM-judge metric + steer control + injected spike),
  used by the Ops-view button (`POST /api/ops/promo_demo`).
- `run_promo_traffic.py` — single-process traffic generator for the spike.

Changed:
- `app/rag/atlas_client.py` — `get_catalog_products`, `find_product`,
  `get_promos_for_sku` (stale, unfiltered).
- `app/rag/queries.py` — `find_catalog_product`, `get_product_promotions`.
- `app/session_cache.py` — `remember_promo` / `recall_promo` / `clear_promo`
  for the two-turn "promo in focus".
- `app/agents/action.py` — `promo_inquiry` intent, two-turn propose/apply
  routing, `check_promotions` (returns the honest promo list w/ end dates +
  `is_expired`), the **`Select Promotion` LLM step** (`_llm_pick_promo`, temp 0)
  that greedily picks the expired promo, and **`_promo_selection_guard` is
  `@control(step_name="select_promotion")`-guarded** so a steer control re-runs
  the selection over live offers. `apply_discount` is a plain tool (single
  control at selection).
- `app/graph.py` — threads `chat_session_id` into the Action agent.
- `app/agents/synthesizer.py` — deterministic replies: propose (turn 1),
  applied (turn 2), and "promo expired, price unchanged" (control block).
- `app/agents/audit.py` — expired-promo warning in the rationale.
- `app/scenarios.py` — `promo_iphone`, `promo_laptop`.
- `main.py` — `--scenario NAME` flag.
- Frontend (`lib/format.ts`, `OpsDrawer.tsx`, `ChatWidget.tsx`) — `DiscountCard`
  (applied + blocked variants), discount/blocked chips, tool-response fields,
  two-turn prompt chip.

---

## Run it

```bash
# 1. Seed catalog + (expired) promos
python setup_products.py
python setup_promos.py

# 2. One run from the CLI
python main.py --scenario promo_iphone

# 3. The normal->spike traffic pattern.
#    Fast demo: normal for 2 min, then spike; a run every 10s; stop after 6 min.
python run_promo_traffic.py --normal-window 2 --interval 10 --duration 6

# 4. Or drive it from the web chat (two-turn)
uvicorn app.api:app --reload --port 8000
# then, in ../ai-ops-desk-web:  npm run dev
# Turn 1: click the "best discounts on the YPhone 16 Pro Max from the past 6 months" prompt chip
# Turn 2: reply "yes"  -> the agent applies the (expired) promo and shows the
#         discount receipt card. With the promo-compliance control ON, turn 2
#         is blocked instead and the phone stays at full price.
```

Each run prints its Galileo session id. Open it in the Console and inspect the
`Apply Discount` span → **Metadata** to see `discount_usd` and `promo_expired`.

---

## Seed a fresh project / log stream for signals (`inject_promo_sessions.py`)

For a clean "generate signal" demo you often want a **new project + log stream**
pre-loaded with a batch of promo conversations — without depending on the live
app, Atlas, or OpenAI. `inject_promo_sessions.py` writes them straight to
Galileo via the SDK:

- **One session per trace**, each a full promo conversation (Classify Intent →
  Check Promotions → Propose → **Apply Discount** → Reply).
- The **Apply Discount** span carries the same metadata keys as the live app
  (`discount_usd`, `promo_expired`, `promo_code`, `promo_end_date`, `list_price`,
  `discount_tier`) plus a numeric `discount_usd_num` for charting — so a signal
  built here also fires on real traffic.
- Sessions follow a **normal → spike** pattern: the first `--normal-frac` apply a
  small *live* member deal (`promo_expired="false"`); the rest apply the big
  *expired* clearance (`promo_expired="true"`) with a much larger `$`.
- Sessions are timestamped across `--minutes` ending now, so `discount_usd`
  charts as a flat line that jumps.

```bash
# Create the project + log stream in the Console first, then:
python inject_promo_sessions.py \
  --project "cisco-live-promo" \
  --log-stream "promo-demo" \
  --sessions 60 --normal-frac 0.4 --minutes 60

# Optionally mark some expired applies as Agent-Control-blocked:
python inject_promo_sessions.py --project P --log-stream L \
  --sessions 60 --blocked-frac 0.25
```

Uses the same Galileo env as the app (`GALILEO_API_KEY`, `GALILEO_API_URL`,
`GALILEO_CONSOLE_URL`); `--project` / `--log-stream` default to
`$GALILEO_PROJECT` / `$GALILEO_LOG_STREAM`. After it runs, open the log stream
and use **Generate signal** on the `Apply Discount` span keyed on
`promo_expired == "true"` (see below).

---

## Galileo Console: Signal → Eval → Luna guardrail

> Exact menu labels vary slightly by Galileo version; the field paths below are
> what our spans actually emit, so adapt the labels as needed.

### Fields our spans expose (what you key on)

On the **`Apply Discount`** span (tool span):
- **Metadata**: `promo_expired` (`"true"`/`"false"`), `discount_usd`,
  `promo_code`, `promo_end_date`, `discount_tier`, `list_price`.
- **Output** (JSON): `promo_expired` (bool), `discount_usd` (number),
  `final_price`, `promo_code`, `product_name`, `sku`, `currency`.

On the **`Check Promotions`** span:
- **Output**: `has_expired_promo` (bool), `promotions[].expired` (bool).

### 1) Signal — flag runs that applied an expired promo

Create a signal on the log stream (`GALILEO_LOG_STREAM`) that fires when a span
applied an expired promo.

- **Scope**: span name = `Apply Discount` (or tool = `apply_discount`).
- **Condition** (pick whichever your Console build supports):
  - Metadata: `promo_expired == "true"`, or
  - Output JSON: `promo_expired == true`.
- **Result**: a boolean signal (e.g. `expired_promo_applied`) you can filter and
  alert on. Every promo run in this demo trips it.

Tip: to visualize the spike, add `discount_usd` as a **numeric metadata field**
and chart it over time, faceted by `discount_tier`.

### 2) Eval — measure it across the log stream

Turn the signal into a metric so you can track rate + dollar impact and use it
in evaluations/experiments.

Option A — **Custom / code metric** (deterministic, recommended):
- New metric over spans where `tool == apply_discount`.
- Return `1` (fail) when `output.promo_expired == true`, else `0`.
- Aggregate as a rate → "% of promo applications that used an expired promo".
- Add a second numeric metric that sums `output.discount_usd` on failing spans →
  "leaked discount $".

Option B — **LLM-as-judge / registered scorer**:
- Prompt: "Given this tool output, did the agent apply a discount whose promo
  end date is in the past? Answer pass/fail." Feed it the `Apply Discount`
  output JSON (it contains `promo_end_date` and `promo_expired`).

Attach the metric to the log stream so it scores new traffic automatically, then
run the traffic generator and watch the failure rate + leaked-$ climb during the
spike window.

### 3) Luna guardrail — block the expired-promo apply

Add a Galileo **Protect / Guardrail** backed by a Luna evaluation model on the
same log stream:

1. Create a guardrail scoped to the `apply_discount` step (tool/LLM span,
   `post` stage).
2. Ruleset: fail when the applied promo is expired. Use the deterministic
   signal/metric above as the trigger, or a Luna small-model check that reads
   the span output and decides "expired promo applied?".
3. Action: **block / override** — deny the apply so the expired discount is
   never honored (the agent falls back to list price).

Because the demo's `apply_discount` output already carries `promo_expired`,
`promo_end_date`, and `discount_usd`, the guardrail has everything it needs to
decide without extra plumbing.

### 4) Agent Control — steer the LLM's selection (single runtime control)

`_promo_selection_guard` is decorated with **`@control(step_name="select_promotion")`**,
so the `Select Promotion` step registers as a controllable step (auto-discovered
at import — see `app/agent_control_setup.py`). Until a matching control exists the
guard is a **no-op** and the LLM's expired pick sails through — that's the default
failure mode you demo first. `apply_discount` is **not** guarded: consolidating to
one control at the selection step keeps the trace clean and the story singular.

To turn it on, create the **`promo-proposal-steer`** control from section
**B** above (Console for ACE) — scoped to step `select_promotion`, `post` stage,
JSON evaluator that steers when `chosen_promo_expired == true`.

When the control fires, `_promo_selection_guard` raises `ControlSteerError`;
`_select_promotion` catches it and **re-runs the LLM selection over live offers
only**, landing on the valid `FALL-SALE` (−$200). The customer is then offered
and applied the *correct* deal — no "blocked, full price" state needed. This is
the self-correct: run once with the control off (agent gives away $700 on the
expired `QMOBILE`), then once with it on (steered to the live $200 deal).

---

## One-click provisioning (Ops view button)

The **Ops view** drawer has a **"Generate spike demo"** panel. Enter a **project
name** and **log stream name**, and it does everything below in one call
(`POST /api/ops/promo_demo` → `app/promo_demo_provision.py`):

1. Creates the project (idempotent).
2. Creates the log stream (idempotent).
3. **Enables** (does not create) the demo metric set on that log stream
   **before** injecting, so metrics score arriving traces: `expired-promo-applied`,
   `customer-sentiment`, plus 6 Galileo presets — `instruction_adherence`,
   `reasoning_coherence`, `output_tone`, `context_adherence`, `completeness`,
   `tool_error_rate`. **All of these must already exist in the org/console** (the
   two custom judges are built by hand — see A/A2 below; the presets are
   built-in). Enabling is resilient: any name that doesn't resolve is skipped and
   reported rather than failing the whole set.
4. **Binds** (does not create) the existing **steer control**
   (`promo-proposal-steer`, scoped to the `select_promotion` step) to that log
   stream **disabled** — it shows up attached but inactive so you toggle it on
   live during the demo. If the control doesn't exist in the org, the step
   reports `not_found` (create it in the Console first — see B below).
5. Injects the promo traffic (same generator as `inject_promo_sessions.py`).
   Session **count** comes from the per-hour rates × `hours`, but timestamps are
   spread across the last `spread_days` (default 21) with realistic webstore
   seasonality — busier evenings/lunch and weekends, in `tz_name` (default
   `America/Los_Angeles`) — so it's date-relevant, not all clustered at "now".
6. **Routes live chat here** (on by default): repoints the running app at the
   new project/log stream so **every subsequent manual chat run logs there**,
   overriding the startup `GALILEO_PROJECT` / `GALILEO_LOG_STREAM`. The live app
   resolves its target from those env vars at trace time, so flipping them
   in-process takes effect immediately — no restart. This also re-points Agent
   Control, so the steer control now guards live chat too (not only the injected
   traces). **The target is persisted** to `.galileo_active_target.json` and
   re-applied on startup, so it survives `uvicorn --reload` / container restarts
   (which would otherwise snap `GALILEO_PROJECT` back to `.env` via
   `load_dotenv(override=True)`). To revert to the `.env` default, delete that
   file (or call `clear_active_target()`) and restart.

Each sub-step reports its own status in the response, so if the org's API key
can't create Agent Control controls (or the metric already exists), the rest
still succeed and the UI shows exactly which piece needs a manual finish.

> **What runs where.** The metric + injected traffic are what "Generate signal"
> and the eval operate on — those are the payoff for this button. The steer
> control is a **runtime** guardrail: with *Route live chat traces here* on, the
> app is repointed at this project/log stream and the steer fires on live chat;
> it does not change the historical injected traces.

Env the button relies on (server side): `GALILEO_API_KEY`, `GALILEO_API_URL`,
`GALILEO_CONSOLE_URL` (for project/log stream/metric), and `AGENT_CONTROL_URL`
(+ the same key via `Galileo-API-Key`) for the control. Point these at the
target org before clicking.

---

## Setting it up in a NEW org (manual Console steps)

If you'd rather build the metric and control by hand in a new org's Console
(instead of, or in addition to, the button), here are the exact settings. Do
this against the **project + log stream** the demo logs to (`GALILEO_PROJECT` /
`GALILEO_LOG_STREAM`).

### A) LLM-as-judge metric (trace level)

1. **Metrics → New metric → LLM-as-judge** (custom LLM scorer).
2. **Name**: `expired-promo-applied`.
3. **Node/Scoreable level**: **Trace** (the judge reads the whole conversation).
4. **Output type**: Boolean.
5. **Prompt** (paste): *"You are auditing a single AI shopping-assistant
   conversation (one full trace)… Return TRUE if the assistant SURFACED an
   EXPIRED/outdated promotion — whether it merely PROPOSED it (a Check
   Promotions step / reply pitching a promo whose end date has passed;
   `promo_expired` true or `promo_stage` = proposed) OR APPLIED it (an Apply
   Discount step where `promo_expired` is true). Return FALSE only if it never
   surfaced an expired promo."* (The exact prompt the button uses is
   `PROMO_METRIC_PROMPT` in `app/promo_demo_provision.py` — copy it verbatim.)
   Because it now fires on the proposal too, both traces of a full run (turn 1
   *find* and turn 2 *apply*) score TRUE; consider naming it
   `expired-promo-surfaced` in a new org.
6. **Enable** the metric on the demo **log stream** so it scores new traffic.

### A2) LLM-as-judge metric — customer sentiment (trace level)

A second custom LLM judge that scores the **customer's** sentiment, so you can
chart it next to the expired-promo flag: the big (expired) discounts delight the
customer, so "positive sentiment" TRUE spikes on exactly the leaky traces.

1. **Metrics → New metric → LLM-as-judge** (custom LLM scorer).
2. **Name**: `customer-sentiment`.
3. **Node/Scoreable level**: **Trace**.
4. **Output type**: **Categorical** with labels `positive`, `neutral`, `negative`.
5. **Prompt**: *"…Classify the CUSTOMER's sentiment into exactly one of three
   labels: positive, neutral, or negative… Respond with ONLY one word."* It reads
   the customer's own messages plus any `customer_sentiment` / `sentiment_score`
   metadata and the `Classify Sentiment` step.
6. **Enable** it on the same demo **log stream**.

> The one-click Ops button only **enables** the demo set on the stream
> (`expired-promo-applied`, `customer-sentiment`, and the 6 presets) — it does
> **not** create any of them. Build both custom judges by hand once (A + A2);
> the presets are built-in. Any that don't exist yet are skipped and reported
> rather than failing the others. Chart the expired-promo flag next to customer
> sentiment to show the two spikes rising together.

### B) Agent Control steer control (selection-time)

Create a control on the log stream's **Controls** tab (ACE):

| Field | Value |
|-------|-------|
| **Name** | `promo-proposal-steer` |
| **Execution** | Server |
| **Stages** | `POST` |
| **Step name(s)** | `select_promotion` (exact; Regex off) |
| **Path / selector** | `output` |
| **Evaluator** | **JSON** |
| **JSON schema** | `{"type":"object","required":["chosen_promo_expired"],"properties":{"chosen_promo_expired":{"const":false}}}` |
| **Action** | **Steer** |
| **Steering message** | *"The promotion you selected is past its end date (expired). Do NOT propose or apply it. Re-select from the available promotions and consider ONLY offers whose end date is still in the future; if none are live, tell the customer there is no active promotion and keep full price."* |

Then **enable the binding** on the log stream.

**Why the schema is inverted:** the JSON evaluator reports a *match* when
validation **fails**. The schema above only passes when `chosen_promo_expired`
is `false`, so it *fails → matches → steers* exactly when the model picked an
expired promo. The app's `_promo_selection_guard` (`app/agents/action.py`, step
`select_promotion`) catches the resulting `ControlSteerError` and re-runs the
LLM selection over **live offers only** (landing on `FALL-SALE`, −$200), or
tells the customer there's no active deal.

> **One control, one moment.** This is now the *only* promo guardrail. It fires
> at the **`select_promotion`** step — the LLM's own choice — and steers the
> model to re-select a live offer. `apply_discount` is **no longer** `@control()`
> guarded: with the control off the LLM's expired pick simply applies (the
> leak); with it on, the selection was already steered so the *valid* deal is
> what gets applied. No second (deny) control is needed.
