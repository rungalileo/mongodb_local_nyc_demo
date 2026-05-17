"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChatResult, StreamEvent, streamChat } from "@/lib/api";
import { Identity } from "@/lib/identity";
import { actionChips, customerMessage } from "@/lib/format";
import {
  AGENT_NAMES,
  AgentName,
  CUSTOMER_LABEL,
} from "@/lib/agentLabels";

export type AgentStatus = "pending" | "running" | "done" | "error";
export type AgentRow = {
  name: AgentName;
  status: AgentStatus;
  elapsedMs?: number;
};
export const AGENTS = AGENT_NAMES;

function freshAgents(): AgentRow[] {
  return AGENTS.map((name) => ({ name, status: "pending" }));
}

export type ChatTurn = {
  role: "user" | "assistant";
  text: string;
  result?: ChatResult;
};

export function ChatWidget({
  me,
  open,
  onOpenChange,
  onAgentsChange,
  onResult,
  drift,
  prefill,
}: {
  me: Identity;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAgentsChange: (a: AgentRow[]) => void;
  onResult: (r: ChatResult | null) => void;
  drift: boolean;
  prefill: { text: string; nonce: number } | null;
}) {
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([
    {
      role: "assistant",
      text: `Hi ${me.name.split(" ")[0]} — I'm Volt, your support assistant. How can I help today?`,
    },
  ]);
  const [busy, setBusy] = useState(false);
  const [liveAgents, setLiveAgents] = useState<AgentRow[] | null>(null);
  // Per-chat identifier. Every turn in this chat uses the same value so the
  // backend records them under one Galileo session. Reset on user switch.
  const [chatSessionId, setChatSessionId] = useState<string>(() =>
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`,
  );
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (prefill && prefill.text) {
      setInput(prefill.text);
      onOpenChange(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill]);

  // Reset welcome message AND chat session id when identity changes (ops
  // drawer user switch). A new customer = a fresh conversation, so the
  // Galileo session should also be fresh.
  useEffect(() => {
    setTurns([
      {
        role: "assistant",
        text: `Hi ${me.name.split(" ")[0]} — I'm Volt, your support assistant. How can I help today?`,
      },
    ]);
    onAgentsChange(freshAgents());
    onResult(null);
    setLiveAgents(null);
    setChatSessionId(
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me.userId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [turns, busy, liveAgents]);

  async function send() {
    const q = input.trim();
    if (!q || busy) return;
    setInput("");
    setTurns((t) => [...t, { role: "user", text: q }]);
    setBusy(true);

    const agents = freshAgents();
    agents[0].status = "running";
    onAgentsChange(agents);
    setLiveAgents(agents);
    onResult(null);

    try {
      let lastAgents = agents;
      for await (const ev of streamChat({
        user_query: q,
        user_id: me.userId,
        toggles: drift ? ["drift"] : [],
        chat_session_id: chatSessionId,
      })) {
        lastAgents = applyEvent(lastAgents, ev);
        onAgentsChange(lastAgents);
        setLiveAgents(lastAgents);
        if (ev.type === "complete") {
          onResult(ev.result);
          const replyText =
            (ev.result.reply && ev.result.reply.trim()) ||
            customerMessage(ev.result);
          setTurns((t) => [
            ...t,
            { role: "assistant", text: replyText, result: ev.result },
          ]);
        } else if (ev.type === "error") {
          setTurns((t) => [
            ...t,
            {
              role: "assistant",
              text: "Something went wrong on my end. Please try again.",
            },
          ]);
        }
      }
    } catch (e) {
      setTurns((t) => [
        ...t,
        {
          role: "assistant",
          text: "I couldn't reach support right now. Please try again.",
        },
      ]);
      console.error(e);
    } finally {
      setBusy(false);
      setLiveAgents(null);
    }
  }

  return (
    <>
      {/* Launcher bubble — hidden while panel is open */}
      <button
        aria-label="Open support chat"
        onClick={() => onOpenChange(true)}
        className={`fixed bottom-5 right-5 z-30 w-14 h-14 rounded-full bg-indigo-600 hover:bg-indigo-700 text-white shadow-lg grid place-items-center transition-all ${
          open ? "opacity-0 pointer-events-none scale-90" : "opacity-100 scale-100 hover:scale-105"
        }`}
      >
        <ChatIcon />
      </button>

      {/* Push-in side panel */}
      <aside
        className={`fixed top-0 right-0 z-40 h-screen w-full md:w-[560px] lg:w-[640px] xl:w-[720px] bg-white dark:bg-zinc-950 border-l border-zinc-200 dark:border-zinc-800 shadow-2xl flex flex-col transform transition-transform duration-300 ease-out ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <div className="px-5 py-4 border-b border-zinc-200 dark:border-zinc-800 flex items-center gap-3 shrink-0">
          <div className="w-9 h-9 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 grid place-items-center text-white text-sm font-bold">
            V
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-semibold leading-tight">Volt Support</div>
            <div className="text-xs text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block" />
              Online · replies instantly
            </div>
          </div>
          <button
            onClick={() => onOpenChange(false)}
            aria-label="Close chat"
            className="text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 p-1.5 rounded-md hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
          >
            <CloseIcon />
          </button>
        </div>

        <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-6 space-y-5">
          {turns.map((t, i) => (
            <Bubble key={i} turn={t} me={me} />
          ))}
          {busy && <ThinkingBubble agents={liveAgents} />}
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
          className="border-t border-zinc-200 dark:border-zinc-800 p-4 flex items-end gap-2 shrink-0 bg-white dark:bg-zinc-950"
        >
          <textarea
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder="Type your message…"
            disabled={busy}
            className="flex-1 resize-none rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 max-h-32 disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2.5 text-sm font-medium disabled:opacity-40 transition-colors"
          >
            Send
          </button>
        </form>
      </aside>
    </>
  );
}

function Bubble({ turn, me }: { turn: ChatTurn; me: Identity }) {
  const isUser = turn.role === "user";
  const chips = turn.result ? actionChips(turn.result.actions) : [];
  return (
    <div className={`flex gap-2 ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser && <Avatar kind="bot" />}
      <div className={`max-w-[85%] ${isUser ? "items-end" : "items-start"} flex flex-col gap-1.5`}>
        <div
          className={`rounded-2xl px-4 py-3 text-[15px] leading-relaxed whitespace-pre-wrap ${
            isUser
              ? "bg-indigo-600 text-white rounded-br-sm"
              : "bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 rounded-bl-sm"
          }`}
        >
          {turn.text}
        </div>
        {chips.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {chips.map((c, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1 text-xs rounded-full border border-emerald-200 dark:border-emerald-900 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 px-2 py-0.5"
              >
                <span>{c.icon}</span>
                {c.label}
              </span>
            ))}
          </div>
        )}
      </div>
      {isUser && <Avatar kind="user" me={me} />}
    </div>
  );
}

function ThinkingBubble({ agents }: { agents: AgentRow[] | null }) {
  // Pick the most recent meaningful step to display.
  const { current, completed } = useMemo(() => {
    if (!agents) return { current: null as AgentRow | null, completed: [] as AgentRow[] };
    const running = agents.find((a) => a.status === "running");
    const done = agents.filter((a) => a.status === "done");
    const fallback = !running ? done[done.length - 1] : null;
    return { current: running ?? fallback, completed: done };
  }, [agents]);

  return (
    <div className="flex gap-2 justify-start">
      <Avatar kind="bot" />
      <div className="rounded-2xl rounded-bl-sm bg-zinc-100 dark:bg-zinc-800 px-4 py-3.5 min-w-[240px]">
        <div className="flex items-center gap-2 text-[15px] text-zinc-700 dark:text-zinc-200">
          <Spinner />
          <span className="font-medium">
            {current ? CUSTOMER_LABEL[current.name] : "Thinking…"}
          </span>
        </div>
        {completed.length > 0 && (
          <ul className="mt-2.5 space-y-1">
            {completed.map((a) => (
              <li
                key={a.name}
                className="flex items-center gap-1.5 text-sm text-zinc-500 dark:text-zinc-400"
              >
                <Check />
                <span className="line-through decoration-zinc-300 dark:decoration-zinc-600 decoration-1">
                  {CUSTOMER_LABEL[a.name].replace(/…$/, "")}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function Spinner() {
  return (
    <span className="relative inline-block w-3.5 h-3.5">
      <span className="absolute inset-0 rounded-full border-2 border-indigo-200 dark:border-indigo-900" />
      <span className="absolute inset-0 rounded-full border-2 border-transparent border-t-indigo-600 dark:border-t-indigo-400 animate-spin" />
    </span>
  );
}

function Check() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className="text-emerald-500 shrink-0">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

function Avatar({ kind, me }: { kind: "bot" | "user"; me?: Identity }) {
  if (kind === "bot") {
    return (
      <div className="shrink-0 w-7 h-7 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 grid place-items-center text-white text-[10px] font-bold">
        V
      </div>
    );
  }
  return (
    <div className="shrink-0 w-7 h-7 rounded-full bg-zinc-200 dark:bg-zinc-700 grid place-items-center text-[10px] font-medium">
      {me?.initials ?? "?"}
    </div>
  );
}

function ChatIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

function applyEvent(rows: AgentRow[], ev: StreamEvent): AgentRow[] {
  if (ev.type !== "agent_done") {
    if (ev.type === "error") {
      return rows.map((r) => (r.status === "running" ? { ...r, status: "error" } : r));
    }
    if (ev.type === "complete") {
      return rows.map((r) => (r.status === "running" ? { ...r, status: "done" } : r));
    }
    return rows;
  }
  const next = [...rows];
  const idx = next.findIndex((a) => a.name === ev.agent);
  if (idx !== -1) {
    next[idx] = { ...next[idx], status: "done", elapsedMs: ev.elapsed_ms };
  }
  const after = next.findIndex((a, i) => i > idx && a.status === "pending");
  if (after !== -1) next[after] = { ...next[after], status: "running" };
  return next;
}
