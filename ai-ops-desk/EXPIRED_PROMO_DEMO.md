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

A customer shops for an expensive catalog item (an 85-inch OLED TV, a pro
laptop, …). The web chat runs a **two-turn** flow:

**Turn 1 — the customer asks:**

> "Any discount on the 85-inch OLED TV?"

The agent:

1. Classifies the intent as `promo_inquiry`.
2. Calls **`check_promotions`**, which reads promos from a **stale cache**
   (`get_product_promotions` deliberately does **not** filter on
   `effective_until`), so promos that ended weeks ago come back looking live.
3. Picks the **biggest dollar discount** to propose — which is the expired 55%
   `CLEARANCE-BLOWOUT`, not the small *live* `MEMBER-SAVE` deal — stashes it as
   the "promo in focus" for this chat session, and asks the customer to confirm:
   *"I found promo CLEARANCE-BLOWOUT saving you $1,375 … want me to apply it?"*

**Turn 2 — the customer says "yes":**

4. The affirmation plus the pending promo routes straight to **`apply_discount`**,
   which applies that exact expired promo, adds the item to the cart, and
   confidently confirms the savings with a **discount receipt card** (list price
   → −discount → new price).

The agent never realizes the promo expired. That gap — a cheerful "you saved
$1,375!" reply on top of an expired-promo signal in the trace — is the whole point.

### The intentional bug

- `app/rag/atlas_client.py::get_promos_for_sku` → `find({"sku": sku})` with **no
  date filter**. This is the "stale promo cache".
- `SPRING-SAVER` and `CLEARANCE-BLOWOUT` seeded by `setup_promos.py` have
  `effective_until` in the **past** (only `MEMBER-SAVE` is live).
- The agent proposes the largest discount, so it reaches for the expired
  clearance over the live member deal.
- `apply_discount` applies the discount regardless of expiry and emits
  `promo_expired: true`.

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
| `discount_usd`  | `"27.45"`      | dollars taken off (the value to chart) |
| `list_price`    | `"2499.99"`    | catalog price before discount |
| `promo_code`    | `"SPRING-SAVER"` | which promo was applied |
| `promo_expired` | `"true"`       | always true in this demo |
| `promo_end_date`| ISO timestamp  | when the promo actually ended (past) |
| `discount_tier` | `"normal"` / `"spike"` | which schedule tier produced it |

The magnitude follows a **time schedule** (`app/promo_spike.py`) anchored to
when the traffic run started:

- **Normal window** (first `PROMO_NORMAL_WINDOW_SECONDS`, default 10 min): small
  seasonal discounts, ~$5–$60 (`SPRING-SAVER`).
- **Spike window** (after that): clearance blowout, 40–65% of list price
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
- `setup_promos.py` — seeds promos (1 live + 2 expired tiers per SKU).
- `run_promo_traffic.py` — single-process traffic generator for the spike.

Changed:
- `app/rag/atlas_client.py` — `get_catalog_products`, `find_product`,
  `get_promos_for_sku` (stale, unfiltered).
- `app/rag/queries.py` — `find_catalog_product`, `get_product_promotions`.
- `app/session_cache.py` — `remember_promo` / `recall_promo` / `clear_promo`
  for the two-turn "promo in focus".
- `app/agents/action.py` — `promo_inquiry` intent, two-turn propose/apply
  routing, `check_promotions` (proposes the biggest discount) / `apply_discount`
  (discount metadata on the span), and **`apply_discount` is now `@control()`-
  guarded** with an expired-promo block + full-price remediation.
- `app/graph.py` — threads `chat_session_id` into the Action agent.
- `app/agents/synthesizer.py` — deterministic replies: propose (turn 1),
  applied (turn 2), and "promo expired, price unchanged" (control block).
- `app/agents/audit.py` — expired-promo warning in the rationale.
- `app/scenarios.py` — `promo_oled_tv`, `promo_laptop`.
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
python main.py --scenario promo_oled_tv

# 3. The normal->spike traffic pattern.
#    Fast demo: normal for 2 min, then spike; a run every 10s; stop after 6 min.
python run_promo_traffic.py --normal-window 2 --interval 10 --duration 6

# 4. Or drive it from the web chat (two-turn)
uvicorn app.api:app --reload --port 8000
# then, in ../ai-ops-desk-web:  npm run dev
# Turn 1: click the "Any discount on the 85-inch OLED TV?" prompt chip
# Turn 2: reply "yes"  -> the agent applies the (expired) promo and shows the
#         discount receipt card. With the promo-compliance control ON, turn 2
#         is blocked instead and the TV stays at full price.
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

### 4) Agent Control — code-side runtime block (like `refund-compliance`)

`apply_discount` is decorated with **`@control()`**, so it registers as a
controllable step named `apply_discount` (auto-discovered at import — see
`app/agent_control_setup.py`). Until a matching control exists, the guard is a
**no-op** and the expired discount goes through — that's the default failure
mode you demo first.

To turn on the block, create a **`promo-compliance`** control (Console for ACE,
or `setup_agent_control.py` for the self-hosted OSS server) that:

1. Is scoped to the step `apply_discount` at the `post` stage.
2. Denies when the step output has `promo_expired == true`.
3. Action: **block / deny**.

When the control fires, `apply_discount` raises `ControlViolationError`;
`_apply_discount_span` catches it and returns a `412` payload that keeps the
customer at **list price** (`discount_usd: 0`, `final_price == list_price`) while
recording `attempted_discount_usd` so the trace/UI still show the loss that was
prevented. The synthesizer then renders the "promo expired, price unchanged"
reply and the UI shows the amber **blocked** discount card. This mirrors the
refund-compliance self-correct: run once with the control off (agent gives away
$1,375), then once with it on (blocked, full price kept).

> The Console Luna guardrail (step 3) and this code-side control (step 4) are two
> independent ways to stop the leak — use whichever the venue's Galileo build
> supports. The signal/eval fields are the same either way.
