const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type User = { id: string };

export type Scenario = {
  name: string;
  user_query: string;
  user_id: string;
};

export type ActionReceipt = {
  tool: string;
  status: number;
  ok: boolean;
  response: Record<string, unknown>;
};

export type ChatResult = {
  status: string;
  error: string | null;
  reply: string | null;
  rationale: string | null;
  actions: ActionReceipt[];
  resolution: string | null;
  galileo_session_id: string | null;
  galileo_session_url: string | null;
};

export type StreamEvent =
  | { type: "agent_done"; agent: string; elapsed_ms: number }
  | { type: "complete"; result: ChatResult }
  | { type: "error"; message: string };

export type PromoDemoRequest = {
  project_name: string;
  log_stream_name?: string;
  mistakes_per_hour?: number;
  hours?: number;
  correct_per_hour?: number;
  spread_days?: number;
  tz_name?: string;
  create_metric?: boolean;
  create_control?: boolean;
  set_active?: boolean;
};

export type PromoDemoResult = {
  ok: boolean;
  error?: string;
  project_name?: string;
  log_stream_name?: string;
  console_url?: string | null;
  metric_name?: string | null;
  steer_control_name?: string | null;
  active_target?: boolean;
  steps?: Record<string, Record<string, unknown>>;
};

export async function createPromoDemo(
  body: PromoDemoRequest,
): Promise<PromoDemoResult> {
  const r = await fetch(`${BASE}/api/ops/promo_demo`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return (await r.json()) as PromoDemoResult;
}

export async function getUsers(): Promise<User[]> {
  const r = await fetch(`${BASE}/api/users`);
  const j = await r.json();
  return j.users || [];
}

export async function getScenarios(): Promise<Scenario[]> {
  const r = await fetch(`${BASE}/api/scenarios`);
  const j = await r.json();
  return j.scenarios || [];
}

export async function* streamChat(body: {
  user_query: string;
  user_id: string;
  toggles?: string[];
  // Stable identifier for this chat conversation. Send the same value on
  // every turn so Galileo records them under one session and metrics can
  // correlate multi-turn flows (e.g. receipt then refund).
  chat_session_id?: string;
}): AsyncGenerator<StreamEvent> {
  const res = await fetch(`${BASE}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.body) throw new Error("No response body");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE messages are separated by \n\n
    let idx;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, idx).trim();
      buffer = buffer.slice(idx + 2);
      if (!raw.startsWith("data:")) continue;
      const json = raw.slice(5).trim();
      if (!json) continue;
      try {
        yield JSON.parse(json) as StreamEvent;
      } catch (e) {
        console.error("Failed to parse SSE event", json, e);
      }
    }
  }
}
