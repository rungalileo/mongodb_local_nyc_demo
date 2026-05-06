import { ActionReceipt, ChatResult } from "./api";

// Build a customer-facing reply from the workflow result. The audit
// `rationale` is an internal audit-trail string ("Customer user_001
// submitted request..."), not something a real shopper should see.
// Prefer tool explanations and resolution-specific summaries.

export function customerMessage(result: ChatResult): string {
  const explainer = result.actions.find(
    (a) => a.tool === "explain_order_state" || a.tool === "explain_refund_state"
  );
  if (explainer) {
    const text = (explainer.response.explanation as string) || "";
    return stripWarning(text).trim();
  }

  const refund = result.actions.find((a) => a.tool === "create_refund_request");
  if (refund && refund.ok) {
    const id = refund.response.refund_request_id as string;
    const amount = refund.response.amount as number;
    const currency = (refund.response.currency as string) || "USD";
    return (
      `I've started a refund for ${currency} ${amount?.toFixed?.(2) ?? amount}. ` +
      `Your reference is ${id}. Funds typically appear in 3–5 business days.`
    );
  }

  const escalate = result.actions.find((a) => a.tool === "escalate_ticket");
  if (escalate && escalate.ok) {
    const id = escalate.response.ticket_id as string;
    return (
      `I've escalated this to a human specialist (ticket ${id}). ` +
      `Someone will reach out shortly — I'm sorry for the trouble.`
    );
  }

  const ticket = result.actions.find(
    (a) => a.tool === "create_ticket" || a.tool === "update_ticket"
  );
  if (ticket && ticket.ok) {
    const id = ticket.response.ticket_id as string;
    return (
      `Got it — I've opened support ticket ${id} so a teammate can follow up. ` +
      `Is there anything else I can help with?`
    );
  }

  if (result.error) {
    return "Sorry, something went wrong on my end. Please try again in a moment.";
  }

  return "Thanks — I've logged your request and someone will be in touch.";
}

// Best-effort cleanup of internal warnings the explainer tools sometimes
// append (e.g. "[WARNING: LLM may have hallucinated...]").
function stripWarning(text: string): string {
  return text.replace(/\s*\[WARNING:[^\]]*\]\s*/gi, " ").replace(/\s+/g, " ");
}

export function actionChips(actions: ActionReceipt[]): {
  icon: string;
  label: string;
}[] {
  return actions
    .map((a) => {
      if (!a.ok) return null;
      if (a.tool === "create_refund_request") {
        const amt = a.response.amount as number;
        const cur = (a.response.currency as string) || "USD";
        return { icon: "↩", label: `Refund issued · ${cur} ${amt}` };
      }
      if (a.tool === "escalate_ticket") {
        return { icon: "⚑", label: "Escalated to specialist" };
      }
      if (a.tool === "create_ticket" || a.tool === "update_ticket") {
        return { icon: "✎", label: `Ticket ${a.response.ticket_id}` };
      }
      return null;
    })
    .filter(Boolean) as { icon: string; label: string }[];
}
