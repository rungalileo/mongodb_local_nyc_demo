"use client";

import { useState } from "react";
import { ChatResult } from "@/lib/api";
import { DEFAULT_USER_ID, identityFor } from "@/lib/identity";
import { Storefront } from "./components/Storefront";
import { ChatWidget, AgentRow } from "./components/ChatWidget";
import { OpsDrawer } from "./components/OpsDrawer";
import { AGENT_NAMES } from "@/lib/agentLabels";

const FRESH: AgentRow[] = AGENT_NAMES.map((name) => ({ name, status: "pending" }));

export default function Home() {
  const [userId, setUserId] = useState(DEFAULT_USER_ID);
  const [agents, setAgents] = useState<AgentRow[]>(FRESH);
  const [result, setResult] = useState<ChatResult | null>(null);
  const [drift, setDrift] = useState(false);
  const [prefill, setPrefill] = useState<{ text: string; nonce: number } | null>(null);
  const [chatOpen, setChatOpen] = useState(false);

  const me = identityFor(userId);

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 overflow-x-clip">
      {/* The assistant is an Intercom-style popup that overlays the page, so the
          storefront stays put (no shift) when the chat opens. `overflow-x-clip`
          prevents horizontal scroll without breaking the sticky header. */}
      <Storefront me={me} />

      <ChatWidget
        me={me}
        open={chatOpen}
        onOpenChange={setChatOpen}
        drift={drift}
        prefill={prefill}
        onAgentsChange={setAgents}
        onResult={setResult}
      />

      <OpsDrawer
        agents={agents}
        result={result}
        me={me}
        drift={drift}
        onDriftChange={setDrift}
        onSwitchUser={setUserId}
        onPrefill={(text) => {
          setPrefill({ text, nonce: Date.now() });
          setChatOpen(true);
        }}
      />
    </div>
  );
}
