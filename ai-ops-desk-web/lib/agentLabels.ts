// Maps backend agent/node names to customer-facing status text.
// The customer never sees the raw node names ("records", "audit") — those
// stay in the ops drawer.

export const AGENT_NAMES = [
  "records",
  "policy",
  "action",
  "audit",
  "synthesizer",
] as const;

export type AgentName = (typeof AGENT_NAMES)[number];

// Short labels for the live in-chat status line.
export const CUSTOMER_LABEL: Record<AgentName, string> = {
  records: "Looking up your account…",
  policy: "Checking our policy…",
  action: "Processing your request…",
  audit: "Double-checking the answer…",
  synthesizer: "Writing your reply…",
};

// Longer labels for the ops drawer timeline.
export const OPS_LABEL: Record<AgentName, string> = {
  records: "Records",
  policy: "Policy",
  action: "Action",
  audit: "Audit",
  synthesizer: "Synthesizer",
};

export const OPS_DESC: Record<AgentName, string> = {
  records: "Pulls user's orders, refunds, tickets",
  policy: "Vector-searches relevant policies",
  action: "Executes tools (refunds, tickets, escalation)",
  audit: "Builds rationale + audit trail",
  synthesizer: "Composes the customer-facing reply",
};
