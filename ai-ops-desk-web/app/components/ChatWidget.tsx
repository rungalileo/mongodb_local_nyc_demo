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

  async function send(overrideText?: string) {
    const q = (overrideText ?? input).trim();
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
            <Bubble
              key={i}
              turn={t}
              me={me}
              isLast={i === turns.length - 1}
              busy={busy}
              onReply={send}
            />
          ))}
          {busy && <ThinkingBubble agents={liveAgents} />}
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
          className="border-t border-zinc-200 dark:border-zinc-800 p-4 shrink-0 bg-white dark:bg-zinc-950"
        >
          <div className="flex flex-wrap gap-2 mb-2">
            {[
              "Can I get the receipt for my bluetooth headphones?",
              "Can you issue me a refund?",
              "Any discount on the 85-inch OLED TV?",
            ].map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                onClick={() => send(suggestion)}
                disabled={busy}
                className="rounded-full border border-zinc-300 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900 hover:bg-zinc-100 dark:hover:bg-zinc-800 px-3 py-1 text-xs text-zinc-700 dark:text-zinc-300 transition-colors disabled:opacity-40"
              >
                {suggestion}
              </button>
            ))}
          </div>
          <div className="flex items-end gap-2">
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
          </div>
        </form>
      </aside>
    </>
  );
}

function Bubble({
  turn,
  me,
  isLast,
  busy,
  onReply,
}: {
  turn: ChatTurn;
  me: Identity;
  isLast?: boolean;
  busy?: boolean;
  onReply?: (text: string) => void;
}) {
  const isUser = turn.role === "user";
  const chips = turn.result ? actionChips(turn.result.actions) : [];
  const receipt = !isUser && turn.result ? findReceipt(turn.result.actions) : null;
  const discount = !isUser && turn.result ? findDiscount(turn.result.actions) : null;
  // Show apply/decline quick replies only under the latest bot turn that is a
  // promo *proposal* (check_promotions proposed a code, nothing applied yet).
  const showPromoReplies =
    !isUser && !!isLast && !!onReply && turn.result
      ? findPromoProposal(turn.result.actions)
      : false;
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
        {receipt && <ReceiptCard receipt={receipt} />}
        {discount && <DiscountCard discount={discount} />}
        {chips.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {chips.map((c, i) => (
              <span
                key={i}
                className={`inline-flex items-center gap-1 text-xs rounded-full border px-2 py-0.5 ${
                  c.tone === "warn"
                    ? "border-amber-200 dark:border-amber-900 bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300"
                    : "border-emerald-200 dark:border-emerald-900 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300"
                }`}
              >
                <span>{c.icon}</span>
                {c.label}
              </span>
            ))}
          </div>
        )}
        {showPromoReplies && (
          <div className="flex flex-wrap gap-1.5 mt-0.5">
            <button
              type="button"
              disabled={busy}
              onClick={() => onReply?.("yes")}
              className="rounded-full border border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/40 hover:bg-emerald-100 dark:hover:bg-emerald-900/50 px-3 py-1 text-xs font-medium text-emerald-700 dark:text-emerald-300 transition-colors disabled:opacity-40"
            >
              Yes, apply it
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => onReply?.("No thanks")}
              className="rounded-full border border-zinc-300 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900 hover:bg-zinc-100 dark:hover:bg-zinc-800 px-3 py-1 text-xs font-medium text-zinc-700 dark:text-zinc-300 transition-colors disabled:opacity-40"
            >
              No thanks
            </button>
          </div>
        )}
      </div>
      {isUser && <Avatar kind="user" me={me} />}
    </div>
  );
}

function findPromoProposal(actions: ChatResult["actions"]): boolean {
  if (!actions) return false;
  // If a discount was applied/blocked this turn, it's not a pending proposal.
  if (actions.some((a) => a.tool === "apply_discount")) return false;
  return actions.some(
    (a) =>
      a.tool === "check_promotions" &&
      a.response &&
      typeof a.response === "object" &&
      Boolean((a.response as { proposed_promo_code?: string }).proposed_promo_code),
  );
}

type ReceiptShape = {
  product_name?: string;
  sku?: string;
  quantity?: number;
  unit_price?: number;
  total_amount?: number;
  currency?: string;
  order_id?: string;
  order_date?: string;
  order_status?: string;
  shipping_address?: {
    street?: string;
    city?: string;
    state?: string;
    postal_code?: string;
    country?: string;
  };
};

function findReceipt(actions: ChatResult["actions"]): ReceiptShape | null {
  if (!actions) return null;
  const hit = actions.find(
    (a) => a.tool === "get_receipt" && a.ok && a.response && typeof a.response === "object",
  );
  return hit ? (hit.response as ReceiptShape) : null;
}

function formatMoney(amount: number | undefined, currency: string | undefined) {
  if (amount === undefined || amount === null) return "—";
  const code = currency || "USD";
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: code }).format(amount);
  } catch {
    return `${code} ${amount.toFixed(2)}`;
  }
}

function formatDate(value: string | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function ReceiptCard({ receipt }: { receipt: ReceiptShape }) {
  const subtotal =
    receipt.unit_price !== undefined && receipt.quantity !== undefined
      ? receipt.unit_price * receipt.quantity
      : receipt.total_amount;
  const addr = receipt.shipping_address || {};
  const addressLine1 = addr.street;
  const addressLine2 = [addr.city, addr.state, addr.postal_code].filter(Boolean).join(", ");
  const addressLine3 = addr.country;

  return (
    <div className="w-full max-w-md rounded-2xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 shadow-sm overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-200 dark:border-zinc-700 bg-gradient-to-r from-indigo-50 to-violet-50 dark:from-indigo-950/40 dark:to-violet-950/40">
        <div>
          <div className="text-[11px] uppercase tracking-wider text-zinc-500 dark:text-zinc-400 font-medium">
            Order receipt
          </div>
          <div className="font-mono text-sm text-zinc-900 dark:text-zinc-100 mt-0.5">
            {receipt.order_id || "—"}
          </div>
        </div>
        {receipt.order_status && (
          <span className="inline-flex items-center text-[11px] uppercase tracking-wider rounded-full px-2.5 py-1 bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 font-medium">
            {receipt.order_status}
          </span>
        )}
      </div>

      <div className="px-4 py-3.5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[15px] font-semibold text-zinc-900 dark:text-zinc-100 truncate">
              {receipt.product_name || "Item"}
            </div>
            {receipt.sku && (
              <div className="text-[11px] font-mono text-zinc-500 dark:text-zinc-400 mt-0.5">
                {receipt.sku}
              </div>
            )}
          </div>
          <div className="text-right shrink-0">
            <div className="text-sm text-zinc-900 dark:text-zinc-100">
              {formatMoney(receipt.unit_price, receipt.currency)}
            </div>
            <div className="text-[11px] text-zinc-500 dark:text-zinc-400 mt-0.5">
              × {receipt.quantity ?? 1}
            </div>
          </div>
        </div>
      </div>

      <div className="px-4 pb-3 border-b border-dashed border-zinc-200 dark:border-zinc-700">
        <div className="flex items-center justify-between text-[13px] text-zinc-600 dark:text-zinc-400">
          <span>Subtotal</span>
          <span className="font-medium text-zinc-800 dark:text-zinc-200">
            {formatMoney(subtotal, receipt.currency)}
          </span>
        </div>
      </div>

      <div className="px-4 py-3 flex items-center justify-between">
        <span className="text-[13px] uppercase tracking-wider text-zinc-500 dark:text-zinc-400 font-medium">
          Total paid
        </span>
        <span className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
          {formatMoney(receipt.total_amount, receipt.currency)}
        </span>
      </div>

      <div className="px-4 py-3 border-t border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-950/40 grid grid-cols-2 gap-x-4 gap-y-2 text-[12px]">
        <div>
          <div className="uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-0.5">
            Purchased
          </div>
          <div className="text-zinc-800 dark:text-zinc-200">{formatDate(receipt.order_date)}</div>
        </div>
        {(addressLine1 || addressLine2) && (
          <div>
            <div className="uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-0.5">
              Ship to
            </div>
            <div className="text-zinc-800 dark:text-zinc-200 leading-tight">
              {addressLine1 && <div>{addressLine1}</div>}
              {addressLine2 && <div>{addressLine2}</div>}
              {addressLine3 && <div>{addressLine3}</div>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

type DiscountShape = {
  product_name?: string;
  sku?: string;
  currency?: string;
  list_price?: number;
  discount_usd?: number;
  final_price?: number;
  promo_code?: string;
  promo_description?: string;
  promo_end_date?: string;
  promo_expired?: boolean;
  discount_tier?: string;
  // Present only on the Agent-Control-blocked payload.
  error?: string;
  attempted_discount_usd?: number;
  attempted_final_price?: number;
};

type DiscountCardData = DiscountShape & { blocked: boolean };

function findDiscount(actions: ChatResult["actions"]): DiscountCardData | null {
  if (!actions) return null;
  const applied = actions.find(
    (a) => a.tool === "apply_discount" && a.ok && a.response && typeof a.response === "object",
  );
  if (applied) return { ...(applied.response as DiscountShape), blocked: false };

  // Blocked by Agent Control: not `ok` (HTTP 412), still worth showing as the
  // "expired, not applied" card so the audience sees the loss that was stopped.
  const blocked = actions.find(
    (a) =>
      a.tool === "apply_discount" &&
      a.response &&
      typeof a.response === "object" &&
      (a.response as DiscountShape).error === "blocked_by_agent_control",
  );
  if (blocked) return { ...(blocked.response as DiscountShape), blocked: true };
  return null;
}

function DiscountCard({ discount }: { discount: DiscountCardData }) {
  const blocked = discount.blocked;
  const currency = discount.currency;
  const listPrice = discount.list_price;
  // On the blocked card, surface what the agent *tried* to give away.
  const savings = blocked ? discount.attempted_discount_usd : discount.discount_usd;
  const finalPrice = blocked ? discount.attempted_final_price : discount.final_price;
  const endDate = formatDate(discount.promo_end_date);

  const accent = blocked
    ? "from-amber-50 to-orange-50 dark:from-amber-950/40 dark:to-orange-950/40"
    : "from-emerald-50 to-teal-50 dark:from-emerald-950/40 dark:to-teal-950/40";

  return (
    <div className="w-full max-w-md rounded-2xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 shadow-sm overflow-hidden">
      <div className={`flex items-center justify-between px-4 py-3 border-b border-zinc-200 dark:border-zinc-700 bg-gradient-to-r ${accent}`}>
        <div>
          <div className="text-[11px] uppercase tracking-wider text-zinc-500 dark:text-zinc-400 font-medium">
            {blocked ? "Promo blocked" : "Discount applied"}
          </div>
          <div className="font-mono text-sm text-zinc-900 dark:text-zinc-100 mt-0.5">
            {discount.promo_code || "—"}
          </div>
        </div>
        <span
          className={`inline-flex items-center text-[11px] uppercase tracking-wider rounded-full px-2.5 py-1 font-medium ${
            blocked
              ? "bg-amber-100 dark:bg-amber-950/60 text-amber-700 dark:text-amber-300"
              : "bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300"
          }`}
        >
          {blocked ? "Expired" : "Added to cart"}
        </span>
      </div>

      <div className="px-4 py-3.5">
        <div className="text-[15px] font-semibold text-zinc-900 dark:text-zinc-100 truncate">
          {discount.product_name || "Item"}
        </div>
        {discount.sku && (
          <div className="text-[11px] font-mono text-zinc-500 dark:text-zinc-400 mt-0.5">
            {discount.sku}
          </div>
        )}
      </div>

      <div className="px-4 pb-3 space-y-1.5 border-b border-dashed border-zinc-200 dark:border-zinc-700">
        <div className="flex items-center justify-between text-[13px] text-zinc-600 dark:text-zinc-400">
          <span>List price</span>
          <span className="font-medium text-zinc-800 dark:text-zinc-200">
            {formatMoney(listPrice, currency)}
          </span>
        </div>
        <div className="flex items-center justify-between text-[13px]">
          <span className={blocked ? "text-zinc-400 dark:text-zinc-500 line-through" : "text-emerald-600 dark:text-emerald-400"}>
            {blocked ? "Discount (not applied)" : `Discount ${discount.promo_code ? `· ${discount.promo_code}` : ""}`}
          </span>
          <span className={blocked ? "font-medium text-zinc-400 dark:text-zinc-500 line-through" : "font-medium text-emerald-600 dark:text-emerald-400"}>
            −{formatMoney(savings, currency)}
          </span>
        </div>
      </div>

      <div className="px-4 py-3 flex items-center justify-between">
        <span className="text-[13px] uppercase tracking-wider text-zinc-500 dark:text-zinc-400 font-medium">
          {blocked ? "You pay" : "New price"}
        </span>
        <span className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
          {blocked ? formatMoney(listPrice, currency) : formatMoney(finalPrice, currency)}
        </span>
      </div>

      {blocked && (
        <div className="px-4 py-2.5 border-t border-zinc-200 dark:border-zinc-700 bg-amber-50/60 dark:bg-amber-950/20 text-[12px] text-amber-800 dark:text-amber-300">
          Agent Control stopped an expired promo{endDate !== "—" ? ` (ended ${endDate})` : ""}. Full price kept.
        </div>
      )}
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
