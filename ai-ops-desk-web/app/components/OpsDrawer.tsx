"use client";

import { useEffect, useState } from "react";
import { ChatResult, Scenario, User, getScenarios, getUsers } from "@/lib/api";
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
                {result.actions.map((a, i) => (
                  <li
                    key={i}
                    className="rounded-md border border-zinc-200 dark:border-zinc-800 p-2.5 text-xs"
                  >
                    <div className="flex items-center gap-2">
                      <span className={a.ok ? "text-emerald-600" : "text-red-600"}>
                        {a.ok ? "✓" : "✗"}
                      </span>
                      <span className="font-mono">{a.tool}</span>
                      <span className="ml-auto text-zinc-500">{a.status}</span>
                    </div>
                    <pre className="mt-1.5 text-[11px] text-zinc-600 dark:text-zinc-400 whitespace-pre-wrap break-words font-mono">
                      {summarizeResponse(a.response)}
                    </pre>
                  </li>
                ))}
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

function summarizeResponse(r: Record<string, unknown>): string {
  const keys = ["refund_request_id", "ticket_id", "amount", "currency", "escalation_level", "customer_sentiment", "explanation"];
  const lines: string[] = [];
  for (const k of keys) {
    if (r[k] !== undefined) {
      let v = String(r[k]);
      if (v.length > 140) v = v.slice(0, 140) + "…";
      lines.push(`${k}: ${v}`);
    }
  }
  return lines.join("\n") || JSON.stringify(r).slice(0, 160);
}
