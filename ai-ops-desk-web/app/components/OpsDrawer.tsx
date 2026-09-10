"use client";

import { useEffect, useState } from "react";
import {
  ChatResult,
  CostDemoStatus,
  PromoDemoResult,
  Scenario,
  User,
  createPromoDemo,
  deleteCostDemoProjects,
  fixCostDemo,
  getCostDemoStatus,
  getScenarios,
  getUsers,
  startCostDemo,
} from "@/lib/api";
import { Identity, identityFor } from "@/lib/identity";
import { AgentRow, AgentStatus } from "./ChatWidget";
import { OPS_LABEL as AGENT_LABEL, OPS_DESC as AGENT_DESC } from "@/lib/agentLabels";

export function OpsDrawer({
  agents,
  result,
  me,
  onSwitchUser,
  drift,
  onDriftChange,
  onPrefill,
}: {
  agents: AgentRow[];
  result: ChatResult | null;
  me: Identity;
  onSwitchUser: (id: string) => void;
  drift: boolean;
  onDriftChange: (v: boolean) => void;
  onPrefill: (text: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [users, setUsers] = useState<User[]>([]);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);

  useEffect(() => {
    getUsers().then(setUsers).catch(() => {});
    getScenarios().then(setScenarios).catch(() => {});
  }, []);

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="fixed top-3 left-4 z-20 text-xs px-2.5 py-1 rounded-md bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 opacity-70 hover:opacity-100"
        aria-label="Open ops drawer"
      >
        👁 Ops view
      </button>

      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/30"
          onClick={() => setOpen(false)}
        />
      )}

      <aside
        className={`fixed top-0 left-0 z-50 h-screen w-[420px] max-w-[100vw] bg-white dark:bg-zinc-950 border-r border-zinc-200 dark:border-zinc-800 shadow-2xl transform transition-transform duration-200 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="h-14 px-4 flex items-center justify-between border-b border-zinc-200 dark:border-zinc-800">
          <div>
            <div className="text-sm font-semibold">Ops view</div>
            <div className="text-xs text-zinc-500">Demo / debug only</div>
          </div>
          <button
            onClick={() => setOpen(false)}
            className="text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 text-xl leading-none"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="h-[calc(100vh-3.5rem)] overflow-y-auto p-4 space-y-6">
          <Section title="View as">
            <select
              value={me.userId}
              onChange={(e) => onSwitchUser(e.target.value)}
              className="w-full rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-1.5 text-sm"
            >
              {users.map((u) => {
                const id = identityFor(u.id);
                return (
                  <option key={u.id} value={u.id}>
                    {id.name} ({u.id})
                  </option>
                );
              })}
            </select>
            <p className="mt-1 text-xs text-zinc-500">
              Switching reseats the customer & resets the chat.
            </p>
          </Section>

          <Section title="Toggles">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={drift}
                onChange={(e) => onDriftChange(e.target.checked)}
              />
              <span>
                <code className="text-xs bg-zinc-100 dark:bg-zinc-800 px-1 rounded">
                  drift
                </code>{" "}
                — force old policy version
              </span>
            </label>
          </Section>

          <Section title="Generate demo traffic">
            <PromoDemoPanel />
          </Section>

          <Section title="Integration cost demo">
            <CostDemoPanel />
          </Section>

          <Section title="Agent timeline">
            <ol className="space-y-2.5">
              {agents.map((a) => (
                <li key={a.name} className="flex items-start gap-2.5">
                  <StatusDot status={a.status} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-sm font-medium">
                        {AGENT_LABEL[a.name]}
                      </span>
                      {a.elapsedMs !== undefined && (
                        <span className="text-xs text-zinc-500 tabular-nums">
                          {a.elapsedMs} ms
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-zinc-500">{AGENT_DESC[a.name]}</p>
                  </div>
                </li>
              ))}
            </ol>
          </Section>

          {result && (
            <Section title="Tool calls">
              {result.actions.length === 0 && (
                <p className="text-xs text-zinc-500">No tools fired.</p>
              )}
              <ul className="space-y-2">
                {result.actions.map((a, i) => {
                  const blocked =
                    a.response?.error === "blocked_by_agent_control";
                  return (
                    <li
                      key={i}
                      className={`rounded-md border p-2.5 text-xs ${
                        blocked
                          ? "border-amber-400 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-700"
                          : "border-zinc-200 dark:border-zinc-800"
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <span
                          className={
                            blocked
                              ? "text-amber-600 dark:text-amber-400"
                              : a.ok
                              ? "text-emerald-600"
                              : "text-red-600"
                          }
                        >
                          {blocked ? "🛡" : a.ok ? "✓" : "✗"}
                        </span>
                        <span className="font-mono">{a.tool}</span>
                        <span className="ml-auto text-zinc-500">
                          {a.status}
                        </span>
                      </div>
                      {blocked && (
                        <div className="mt-1.5 space-y-1">
                          <div className="text-[11px] font-semibold text-amber-800 dark:text-amber-300">
                            Blocked by Agent Control · control:{" "}
                            <code className="font-mono">
                              {String(a.response?.control_name ?? "unknown")}
                            </code>
                          </div>
                          {typeof a.response?.message === "string" && (
                            <div className="rounded border border-amber-300 dark:border-amber-700 bg-amber-100/60 dark:bg-amber-900/30 px-2 py-1.5 text-[11px] text-amber-900 dark:text-amber-100">
                              {stripControlPrefix(
                                String(a.response.message),
                                String(a.response?.control_name ?? ""),
                              )}
                            </div>
                          )}
                        </div>
                      )}
                      <pre className="mt-1.5 text-[11px] text-zinc-600 dark:text-zinc-400 whitespace-pre-wrap break-words font-mono">
                        {summarizeResponse(a.response, { skip: blocked ? ["message", "control_name"] : [] })}
                      </pre>
                    </li>
                  );
                })}
              </ul>
            </Section>
          )}

          {result?.rationale && (
            <Section title="Audit rationale (raw)">
              <p className="text-xs whitespace-pre-wrap leading-relaxed text-zinc-600 dark:text-zinc-400">
                {result.rationale}
              </p>
            </Section>
          )}

          {result?.galileo_session_url && (
            <Section title="Observability">
              <a
                href={result.galileo_session_url}
                target="_blank"
                rel="noreferrer"
                className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline"
              >
                View session in Galileo →
              </a>
              <p className="mt-1 text-xs text-zinc-500 font-mono break-all">
                {result.galileo_session_id}
              </p>
            </Section>
          )}

          <Section title="Try a scenario">
            <div className="flex flex-wrap gap-1.5">
              {scenarios.map((s) => (
                <button
                  key={s.name}
                  onClick={() => {
                    onSwitchUser(s.user_id);
                    onPrefill(s.user_query);
                    setOpen(false);
                  }}
                  className="text-xs px-2 py-1 rounded-md border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-left"
                  title={s.user_query}
                >
                  {s.name}
                </button>
              ))}
            </div>
            <p className="mt-2 text-xs text-zinc-500">
              Loads the matching customer and pre-fills the chat.
            </p>
          </Section>
        </div>
      </aside>
    </>
  );
}

function PromoDemoPanel() {
  const [projectName, setProjectName] = useState("discount-demo");
  const [logStreamName, setLogStreamName] = useState("Default");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PromoDemoResult | null>(null);

  const submit = async () => {
    if (!projectName.trim() || busy) return;
    setBusy(true);
    setResult(null);
    try {
      const r = await createPromoDemo({
        project_name: projectName.trim(),
        log_stream_name: logStreamName.trim() || "Default",
      });
      setResult(r);
    } catch (e) {
      setResult({ ok: false, error: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  const stepStatus = (key: string): string | undefined => {
    const step = result?.steps?.[key] as Record<string, unknown> | undefined;
    return step?.status as string | undefined;
  };

  return (
    <div className="space-y-2.5">
      <p className="text-xs text-zinc-500">
        Creates the Galileo project + log stream, enables the demo evals
        (expired-promo, customer-sentiment + presets), attaches the
        <code className="mx-1">promo-proposal-steer</code> control (disabled),
        then injects promo conversations — expired-promo mistakes mixed with
        correct live-promo runs, spread across the last few weeks with realistic
        webstore seasonality (busier evenings/weekends).
      </p>

      <label className="block">
        <span className="text-[11px] text-zinc-500">Project name</span>
        <input
          value={projectName}
          onChange={(e) => setProjectName(e.target.value)}
          disabled={busy}
          className="mt-0.5 w-full rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-1.5 text-sm disabled:opacity-50"
          placeholder="discount-demo"
        />
      </label>

      <label className="block">
        <span className="text-[11px] text-zinc-500">Log stream name</span>
        <input
          value={logStreamName}
          onChange={(e) => setLogStreamName(e.target.value)}
          disabled={busy}
          className="mt-0.5 w-full rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-1.5 text-sm disabled:opacity-50"
          placeholder="Default"
        />
      </label>

      <button
        onClick={submit}
        disabled={busy || !projectName.trim()}
        className="w-full rounded-md bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium px-3 py-2 transition-colors disabled:opacity-40"
      >
        {busy ? "Injecting…" : "Create project + inject traffic"}
      </button>

      {result && (
        <div
          className={`rounded-md border p-2.5 text-xs space-y-1 ${
            result.ok
              ? "border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/30"
              : "border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/30"
          }`}
        >
          {result.ok ? (
            <>
              <div className="font-semibold text-emerald-700 dark:text-emerald-300">
                ✓ Provisioned {result.project_name} / {result.log_stream_name}
              </div>
              <StepLine label="Project" status={stepStatus("project")} />
              <StepLine label="Log stream" status={stepStatus("log_stream")} />
              <StepLine label="Evals" status={stepStatus("metric")} />
              <StepLine label="Steer control" status={stepStatus("steer_control")} />
              <StepLine label="Injection" status={stepStatus("injection")} />
              <StepLine label="Live routing" status={stepStatus("set_active")} />
              {(() => {
                const inj = result.steps?.injection as
                  | Record<string, unknown>
                  | undefined;
                if (!inj) return null;
                return (
                  <div className="text-[11px] text-zinc-600 dark:text-zinc-400">
                    {String(inj.expired_applied ?? "?")} expired promos applied ·
                    leak ≈ USD {String(inj.leaked_discount_usd ?? "?")}
                  </div>
                );
              })()}
              {result.console_url && (
                <a
                  href={result.console_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-block mt-1 text-indigo-600 dark:text-indigo-400 hover:underline"
                >
                  Open Galileo console →
                </a>
              )}
              <p className="text-[11px] text-zinc-500">
                In the console, open the log stream and click{" "}
                <b>Generate signal</b> on the “Apply Discount” span
                (promo_expired == true).
              </p>
              {result.active_target && (
                <p className="text-[11px] text-emerald-700 dark:text-emerald-300">
                  Live chat now logs to this project — new manual runs appear
                  here (env project overridden).
                </p>
              )}
            </>
          ) : (
            <div className="text-red-700 dark:text-red-300">
              ✗ {result.error || "Provisioning failed"}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function CostDemoPanel() {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [status, setStatus] = useState<CostDemoStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const [testMode, setTestMode] = useState(false);
  const [llmProject, setLlmProject] = useState("Cost_Sandbox_LLM");
  const [lunaProject, setLunaProject] = useState("Cost_Sandbox_Luna");
  const [deleteMsg, setDeleteMsg] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const running = status?.state === "running" || starting;

  // Poll status while a run is active.
  useEffect(() => {
    if (status?.state !== "running") return;
    const id = setInterval(() => {
      getCostDemoStatus().then(setStatus).catch(() => {});
    }, 2500);
    return () => clearInterval(id);
  }, [status?.state]);

  // On mount, pick up any run already in progress (survives drawer close).
  useEffect(() => {
    getCostDemoStatus()
      .then((s) => {
        if (s && s.state !== "idle") setStatus(s);
      })
      .catch(() => {});
  }, []);

  const run = async () => {
    if (running) return;
    setStarting(true);
    setDeleteMsg(null);
    try {
      const r = await startCostDemo({
        start: start.trim() || undefined,
        end: end.trim() || undefined,
        llm_project: testMode ? llmProject.trim() || undefined : undefined,
        luna_project: testMode ? lunaProject.trim() || undefined : undefined,
      });
      if (!r.started) {
        setStatus({
          state: "error",
          error: r.reason || "could not start",
          steps: [],
        });
      } else {
        const s = await getCostDemoStatus();
        setStatus(s);
      }
    } catch (e) {
      setStatus({
        state: "error",
        error: e instanceof Error ? e.message : String(e),
        steps: [],
      });
    } finally {
      setStarting(false);
    }
  };

  const fix = async () => {
    if (running) return;
    setStarting(true);
    setDeleteMsg(null);
    try {
      const r = await fixCostDemo({
        llm_project: testMode ? llmProject.trim() || undefined : undefined,
        luna_project: testMode ? lunaProject.trim() || undefined : undefined,
        start: start.trim() || undefined,
        end: end.trim() || undefined,
      });
      if (!r.started) {
        setStatus({ state: "error", error: r.reason || "could not start", steps: [] });
      } else {
        setStatus(await getCostDemoStatus());
      }
    } catch (e) {
      setStatus({
        state: "error",
        error: e instanceof Error ? e.message : String(e),
        steps: [],
      });
    } finally {
      setStarting(false);
    }
  };

  const deleteTestProjects = async () => {
    if (deleting || running) return;
    setDeleting(true);
    setDeleteMsg(null);
    try {
      const r = await deleteCostDemoProjects([
        llmProject.trim(),
        lunaProject.trim(),
      ]);
      if (r.error) {
        setDeleteMsg(`Error: ${r.error}`);
      } else {
        const parts = Object.entries(r.results ?? {}).map(
          ([n, v]) => `${n}: ${v.status}`,
        );
        setDeleteMsg(parts.join(" · ") || "Nothing to delete");
      }
    } catch (e) {
      setDeleteMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setDeleting(false);
    }
  };

  const win = status?.window;

  return (
    <div className="space-y-2.5">
      <p className="text-xs text-zinc-500">
        Extends the <code>LLM_Evals</code> (~$1,830/1M) and{" "}
        <code>Luna_Evals</code> (~$80/1M) cost curves from where they dropped to
        $0 up to now. Runs in two phases (sets the evaluator price, injects
        identical-timestamp traffic, waits for scoring), then removes the price
        override.
      </p>

      <label className="flex items-center gap-2 text-xs">
        <input
          type="checkbox"
          checked={testMode}
          onChange={(e) => setTestMode(e.target.checked)}
          disabled={running}
        />
        <span>
          Test mode — target throwaway projects (same metrics), deletable after
        </span>
      </label>

      {testMode && (
        <div className="space-y-2 rounded-md border border-dashed border-zinc-300 dark:border-zinc-700 p-2">
          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span className="text-[11px] text-zinc-500">LLM test project</span>
              <input
                value={llmProject}
                onChange={(e) => setLlmProject(e.target.value)}
                disabled={running}
                className="mt-0.5 w-full rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-1.5 text-sm disabled:opacity-50"
              />
            </label>
            <label className="block">
              <span className="text-[11px] text-zinc-500">Luna test project</span>
              <input
                value={lunaProject}
                onChange={(e) => setLunaProject(e.target.value)}
                disabled={running}
                className="mt-0.5 w-full rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-1.5 text-sm disabled:opacity-50"
              />
            </label>
          </div>
          <p className="text-[11px] text-zinc-500">
            Created on first run (metrics enabled automatically). No existing
            data → backfills ~14 days so there’s a curve to see.
          </p>
          <button
            onClick={deleteTestProjects}
            disabled={deleting || running}
            className="w-full rounded-md border border-red-300 dark:border-red-800 text-red-700 dark:text-red-300 hover:bg-red-50 dark:hover:bg-red-950/30 text-xs font-medium px-3 py-1.5 disabled:opacity-40"
          >
            {deleting ? "Deleting…" : "Delete these test projects"}
          </button>
          {deleteMsg && (
            <div className="text-[11px] text-zinc-600 dark:text-zinc-400 break-words">
              {deleteMsg}
            </div>
          )}
        </div>
      )}
      <p className="text-[11px] text-amber-600 dark:text-amber-400">
        ⚠ While running (a few minutes), the org-wide <code>gpt-5-nano</code>{" "}
        price is temporarily changed. Any live traffic scored on that model in
        this window freezes at the demo price. It’s reset automatically at the
        end.
      </p>

      <div className="grid grid-cols-2 gap-2">
        <label className="block">
          <span className="text-[11px] text-zinc-500">Start (optional)</span>
          <input
            value={start}
            onChange={(e) => setStart(e.target.value)}
            disabled={running}
            className="mt-0.5 w-full rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-1.5 text-sm disabled:opacity-50"
            placeholder="auto"
          />
        </label>
        <label className="block">
          <span className="text-[11px] text-zinc-500">End (optional)</span>
          <input
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            disabled={running}
            className="mt-0.5 w-full rounded-md border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-1.5 text-sm disabled:opacity-50"
            placeholder="auto (now)"
          />
        </label>
      </div>
      <p className="text-[11px] text-zinc-500">
        Blank = continue from the last non-$0 day → now, ~20 traces/day.
      </p>

      <button
        onClick={run}
        disabled={running}
        className="w-full rounded-md bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium px-3 py-2 transition-colors disabled:opacity-40"
      >
        {running ? "Running…" : "Extend cost graph"}
      </button>

      <button
        onClick={fix}
        disabled={running}
        className="w-full rounded-md border border-indigo-300 dark:border-indigo-800 text-indigo-700 dark:text-indigo-300 hover:bg-indigo-50 dark:hover:bg-indigo-950/30 text-sm font-medium px-3 py-2 transition-colors disabled:opacity-40"
      >
        {running ? "Running…" : "Fix scoring gaps"}
      </button>
      <p className="text-[11px] text-zinc-500">
        Scans both projects and heals whichever dipped (from evaluator system
        errors): re-injects the broken window at its correct price — LLM_Evals @
        $1,830 and/or Luna_Evals @ $80 — then resets. Auto-detects the window,
        or use Start/End above. Healthy projects are skipped.
      </p>

      {status && status.state !== "idle" && (
        <div
          className={`rounded-md border p-2.5 text-xs space-y-1.5 ${
            status.state === "error"
              ? "border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/30"
              : status.state === "done"
              ? "border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/30"
              : "border-zinc-200 dark:border-zinc-800"
          }`}
        >
          <div className="flex items-center gap-2 font-semibold">
            {status.state === "running" && (
              <span className="text-amber-600 dark:text-amber-400">
                ● {status.phase ? `Phase: ${status.phase}` : "Running…"}
              </span>
            )}
            {status.state === "done" && (
              <span className="text-emerald-700 dark:text-emerald-300">
                ✓ Cost graph extended
              </span>
            )}
            {status.state === "error" && (
              <span className="text-red-700 dark:text-red-300">✗ Failed</span>
            )}
          </div>

          {win && (
            <div className="text-[11px] text-zinc-600 dark:text-zinc-400">
              {win.traces} traces · {win.days}d · {win.start.slice(0, 10)} →{" "}
              {win.end.slice(0, 10)}
            </div>
          )}

          {(status.steps ?? []).map((s, i) => (
            <div key={i} className="flex items-start gap-1.5">
              <StepIcon status={s.status} />
              <div className="flex-1 min-w-0">
                <div className="text-zinc-700 dark:text-zinc-300">{s.label}</div>
                {s.detail && (
                  <div className="text-[11px] text-zinc-500 break-words">
                    {s.detail}
                  </div>
                )}
              </div>
            </div>
          ))}

          {status.error && (
            <div className="text-red-700 dark:text-red-300 break-words">
              {status.error}
            </div>
          )}

          {status.summary && status.state === "done" && (
            <pre className="mt-1 text-[11px] text-zinc-600 dark:text-zinc-400 whitespace-pre-wrap break-words font-mono">
              {JSON.stringify(status.summary, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

function StepIcon({ status }: { status: string }) {
  const ok = status === "ok";
  const err = status === "error";
  const icon = ok ? "✓" : err ? "✗" : "●";
  const color = ok
    ? "text-emerald-600 dark:text-emerald-400"
    : err
    ? "text-red-600 dark:text-red-400"
    : "text-amber-600 dark:text-amber-400 animate-pulse";
  return <span className={`mt-0.5 ${color}`}>{icon}</span>;
}

function StepLine({
  label,
  status,
}: {
  label: string;
  status: string | undefined;
}) {
  const ok = status === "ok" || status === "created" || status === "exists";
  const skipped = status === "skipped";
  const icon = ok ? "✓" : skipped ? "–" : "⚠";
  const color = ok
    ? "text-emerald-600 dark:text-emerald-400"
    : skipped
    ? "text-zinc-400"
    : "text-amber-600 dark:text-amber-400";
  return (
    <div className="flex items-center gap-1.5">
      <span className={color}>{icon}</span>
      <span className="text-zinc-600 dark:text-zinc-400">{label}</span>
      <span className="ml-auto font-mono text-[11px] text-zinc-500">
        {status ?? "?"}
      </span>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <h3 className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500 mb-2">
        {title}
      </h3>
      {children}
    </div>
  );
}

function StatusDot({ status }: { status: AgentStatus }) {
  const cls =
    status === "done"
      ? "bg-emerald-500"
      : status === "running"
      ? "bg-amber-500 animate-pulse"
      : status === "error"
      ? "bg-red-500"
      : "bg-zinc-300 dark:bg-zinc-700";
  return <span className={`mt-1.5 inline-block w-2 h-2 rounded-full ${cls}`} />;
}

function stripControlPrefix(message: string, controlName: string): string {
  // SDK formats messages as: "Control violation [<name>]: <reason>".
  // We already render the control name above; show just the reason.
  const prefix = `Control violation [${controlName}]:`;
  if (message.startsWith(prefix)) return message.slice(prefix.length).trim();
  const generic = /^Control violation \[[^\]]+\]:\s*/;
  return message.replace(generic, "");
}

function summarizeResponse(
  r: Record<string, unknown>,
  opts: { skip?: string[] } = {},
): string {
  const skip = new Set(opts.skip ?? []);
  const keys = [
    "refund_request_id",
    "ticket_id",
    "amount",
    "currency",
    "escalation_level",
    "customer_sentiment",
    "explanation",
    // Receipt tool fields.
    "order_id",
    "product_name",
    "sku",
    "quantity",
    "unit_price",
    "total_amount",
    "order_date",
    "order_status",
    // Refund-compliance signals on create_refund_request output.
    "receipt_amount",
    "receipt_order_id",
    "amount_matches_receipt",
    // Promo / discount tool fields.
    "list_price",
    "discount_usd",
    "final_price",
    "promo_code",
    "promo_expired",
    "promo_end_date",
    "discount_tier",
    "has_expired_promo",
    // Surfaced on a promo blocked by Agent Control: what the agent tried to give.
    "attempted_discount_usd",
    "attempted_final_price",
    // Agent Control fields surface when a tool is blocked by a control.
    "message",
    "control_name",
    "control_message",
  ];
  const lines: string[] = [];
  for (const k of keys) {
    if (skip.has(k)) continue;
    if (r[k] !== undefined) {
      let v = String(r[k]);
      if (v.length > 140) v = v.slice(0, 140) + "…";
      lines.push(`${k}: ${v}`);
    }
  }
  return lines.join("\n") || JSON.stringify(r).slice(0, 160);
}
