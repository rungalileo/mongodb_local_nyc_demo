# Integration Cost Demo (LLM-as-judge vs Luna)

A standalone helper for driving the Galileo Console's **Integration costs →
LLM Evaluator Costs** view with believable numbers — *without* running up a real
bill. Use it to tell the "LLM-as-judge is expensive, Luna is cheap" story with
two side-by-side projects whose cost graphs share identical timestamps.

> This folder is self-contained and **not** imported by the app. Deleting it
> does not affect the live demo. The Ops-button injector is a different script
> (`../inject_promo_sessions.py`).

---

## The idea in one paragraph

The cost view multiplies **how many evaluator tokens a project consumed** by the
**price you configured for that evaluator model** (org-wide, in Console
settings). Those are two independent dials:

| Dial | Drives | Where you set it | Costs real money? |
|------|--------|------------------|-------------------|
| **Trace count** | *Real* eval spend (tokens actually scored) | `--traces` here | Yes — keep it small |
| **Model price** | *Displayed* dollar figure on the graph | Console → model pricing | No — pure cosmetics |

So: run the judges on a **cheap** model, inject a **modest** number of traces,
then **inflate that model's displayed price** to hit whatever headline number
you want on screen. Your real spend only tracks `count × the cheap model's real
price`; the inflated price is a display-only overlay.

---

## Prerequisites

1. The app's virtualenv at `../.venv` (this script uses the same deps as the app).
2. Galileo creds in `../.env`: `GALILEO_API_KEY`, `GALILEO_API_URL`,
   `GALILEO_CONSOLE_URL`. The script self-locates that `.env`, so you can run it
   from any directory.
3. **Create the target project + log stream in the Console first** (the script
   logs into them; it does not create them).
4. **Enable a few LLM-as-judge metrics** on that project (e.g. Correctness,
   Completeness, Instruction Adherence, Input/Output Toxicity) and point them at
   the evaluator model you intend to price. `--num-metrics` here is only used
   for the printed *estimates* — it does not enable anything.

---

## Quick start

From `ai-ops-desk/`:

```bash
# 1) Preview the traffic plan + price/real-spend estimates (sends nothing)
./.venv/bin/python integration-cost-demo/inject_cost_traces.py \
    --dry-run --traces 1000 --num-metrics 5

# 2) Inject into the LLM-judge project (metrics enabled on a CHEAP model)
./.venv/bin/python integration-cost-demo/inject_cost_traces.py \
    --project "LLM-evals" --log-stream "Default" \
    --traces 1000 --num-metrics 5 --end "2026-08-20T15:00:00"
```

The script prints a **`Resolved --end`** line. Copy that exact value for the
second run so both projects get byte-identical timestamps.

---

## The two-project (LLM vs Luna) overlay

To show two different prices on the same chart shape, the two projects must run
their evaluators on **two different models** (pricing is per-model, org-wide):

1. **LLM-judge project** — metrics on, say, `gpt-4o-mini`. In Console, set that
   model's price high (e.g. `$220/1M`) so the graph reads in the thousands.
2. **Luna project** — metrics on Luna (or another model), price left at the real
   Luna rate (`~$0.16/1M`).

Run the injector **twice with the same `--seed`, `--start`, `--end`, `--tz`, and
`--traces`** so the timestamps line up exactly:

```bash
# LLM-judge project
./.venv/bin/python integration-cost-demo/inject_cost_traces.py \
    --project "LLM-evals" --log-stream "Default" \
    --traces 1000 --num-metrics 5 --seed 7 --end "2026-08-20T15:00:00"

# Luna project — SAME window/seed => identical overlay
./.venv/bin/python integration-cost-demo/inject_cost_traces.py \
    --project "Luna-evals" --log-stream "Default" \
    --traces 1000 --num-metrics 5 --seed 7 --end "2026-08-20T15:00:00"
```

> ⚠️ Don't rely on the default "now" end time twice — it drifts between runs.
> Always pass the printed `--end` on the second run.

---

## Flags

| Flag | Default | Purpose |
|------|---------|---------|
| `--project` | `$GALILEO_PROJECT` or `LLM-evals` | Target project (must already exist) |
| `--log-stream` | `$GALILEO_LOG_STREAM` or `Default` | Target log stream |
| `--traces` | `1000` | Total traces spread across the window (drives real spend) |
| `--num-metrics` | `5` | # enabled metrics — **estimate only**, enables nothing |
| `--start` | `2026-07-01` | Window start (local date/datetime) |
| `--end` | now | Window end; pass the printed value to reproduce a run |
| `--tz` | `America/Los_Angeles` | Timezone shaping the diurnal/weekly curve |
| `--model` | `gpt-4o` | Cosmetic model name stamped on spans |
| `--input-tokens` / `--output-tokens` | derived | Override the cosmetic per-trace token stamp |
| `--event-day` / `--event-mult` | — | Multiply traffic on a specific day (e.g. a sale) |
| `--body-repeats` | `1` | Pad transcript text to raise eval token usage |
| `--seed` | `7` | RNG seed — **must match** across the two overlay runs |
| `--flush-every` | `25` | Flush cadence |
| `--dry-run` | off | Print plan + estimates, send nothing |

---

## Reading the dry-run output

- **`Resolved --end`** — the anchor to reuse for an identical second run.
- **Traffic plan** — days covered, avg/peak per day, and the assumed eval tokens.
- **Displayed cost** — the per-1M price to set in Console to hit a given peak-day
  and month-total figure. Remember: over a ~50-day spread,
  `peak_day_cost ≈ month_total / 33`, so a $1K Sunday peak implies a ~$33K month
  header. Use a shorter window or `--event-day` if you want a smaller total.
- **Real eval spend** — what the batch actually costs on each candidate model.
  This is your true bill; keep the model cheap.

---

## Cost math (calibration)

Empirically, a real run displayed **$1,918.52** at **$220/1M** (both input and
output fields) for **500 traces × 5 metrics** ⇒ ~**8.72M** eval tokens ⇒
~**3,480 eval tokens per metric-run**. That constant (`CAL_EVAL_TOKENS_PER_METRIC`
in the script) backs every estimate the dry-run prints. Re-calibrate it if your
metrics' prompts change materially.

---

## Caveats

- **Evaluators still run for real.** Injecting is free, but each enabled metric
  scores every trace, spending real evaluator tokens on the org budget
  (~$2–4 for 1,000 traces on `gpt-4o-mini`/`gpt-5-nano`; ~$52 on GPT-5). Always
  point the target project's metrics at a cheap model.
- **Pricing is per-model, org-wide.** Inflating a model's price affects *every*
  project using that model — which is exactly why the two overlay projects must
  use two different evaluator models.
