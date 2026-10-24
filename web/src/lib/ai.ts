import type { AgentEvent, DeskSnapshot, Focus, ROUTES } from "../../server/ai";

export type { AgentEvent } from "../../server/ai";
type AiConfig = { enabled: boolean; routes: typeof ROUTES; maxSteps: number; maxCostUsd: number };
export type ChatTurn = { role: "user" | "assistant"; content: string };

export async function getAiConfig(): Promise<AiConfig> {
  const response = await fetch("/ai/config");
  if (!response.ok) throw new Error("AI layer unavailable");
  return response.json();
}

export type { Focus } from "../../server/ai";

/** Streams the agent's NDJSON events for one question. With `focus`, it's point & ask (always Haiku). */
export async function streamChat(
  body: { messages: ChatTurn[]; snapshot: DeskSnapshot; focus?: Focus },
  onEvent: (event: AgentEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch(body.focus ? "/ai/ask" : "/ai/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal });
  if (!response.ok || !response.body) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.message ?? `AI request failed (${response.status})`);
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let newline: number;
    while ((newline = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (line) onEvent(JSON.parse(line) as AgentEvent);
    }
  }
}
