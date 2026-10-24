import { useQuery } from "@tanstack/react-query";
import { ArrowUp, Check, Loader2, Square, SquarePen, X, AlertTriangle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import { getAiConfig, streamChat, type AgentEvent, type ChatTurn } from "@/lib/ai";
import { captureDesk } from "@/lib/desk";
import type { ProductClass } from "@/lib/tm";
import { cn } from "@/lib/utils";
import { Mascot } from "./Mascot";

export type ToolStep = { kind: "tool"; callId: string; name: string; args: string; status: "running" | "ok" | "error"; preview?: string };
export type TextPart = { kind: "text"; id: string; text: string };
export type Turn =
  | { role: "user"; content: string }
  | {
      role: "assistant";
      parts: (TextPart | ToolStep)[];
      route?: Extract<AgentEvent, { type: "route" }>;
      usage?: Extract<AgentEvent, { type: "usage" }>;
      error?: string;
      state: "streaming" | "done" | "stopped";
    };

export type DeskContext = {
  symbol: string;
  name?: string;
  productClass: ProductClass;
  assetClass: "crypto" | "stock";
  chartTimeframe: string;
  hasPerp: boolean;
};

function parseArgs(raw: string): Record<string, unknown> {
  try {
    return JSON.parse(raw) ?? {};
  } catch {
    return {};
  }
}

function toolLabel(step: ToolStep): string {
  const a = parseArgs(step.args);
  const s = (a.symbol as string | undefined)?.toUpperCase() ?? "";
  switch (step.name) {
    case "get_desk_snapshot":
      return "Read your screen: price, order flow, book";
    case "get_price_history":
      return `Price history · ${s} ${a.timeframe ?? ""}`;
    case "get_indicator":
      return `${String(a.indicator ?? "indicator").toUpperCase()}${a.period ? ` ${a.period}` : ""} · ${s} ${a.timeframe ?? ""}`;
    case "get_perp_stats":
      return `Funding & open interest · ${s}`;
    case "get_news":
      return `Headlines · ${s}`;
    case "get_market_movers":
      return `Market movers · ${a.kind ?? ""}`;
    default:
      return step.name;
  }
}

function suggestions(symbol: string, hasPerp: boolean): string[] {
  return [
    `What's happening with ${symbol} right now?`,
    hasPerp ? `Is order flow confirming the ${symbol} move, or diverging from it?` : `How volatile has ${symbol} been today?`,
    hasPerp ? `What do funding and open interest say about ${symbol} positioning?` : `What are the key levels on the ${symbol} 1h chart?`,
    `Any headlines that explain ${symbol}'s last 24h?`,
  ];
}

export function apply(turn: Extract<Turn, { role: "assistant" }>, event: AgentEvent): Extract<Turn, { role: "assistant" }> {
  const parts = [...turn.parts];
  switch (event.type) {
    case "text": {
      const i = parts.findIndex((p) => p.kind === "text" && p.id === event.id);
      const part: TextPart = { kind: "text", id: event.id, text: event.text };
      if (i >= 0) parts[i] = part;
      else parts.push(part);
      return { ...turn, parts };
    }
    case "tool_call": {
      const i = parts.findIndex((p) => p.kind === "tool" && p.callId === event.callId);
      const previous = i >= 0 ? (parts[i] as ToolStep) : undefined;
      const step: ToolStep = { kind: "tool", callId: event.callId, name: event.name, args: event.arguments, status: previous?.status === "ok" || previous?.status === "error" ? previous.status : "running" };
      if (i >= 0) parts[i] = { ...previous, ...step };
      else parts.push(step);
      return { ...turn, parts };
    }
    case "tool_result": {
      const i = parts.findIndex((p) => p.kind === "tool" && p.callId === event.callId);
      if (i >= 0) parts[i] = { ...(parts[i] as ToolStep), status: event.ok ? "ok" : "error", preview: event.preview };
      return { ...turn, parts };
    }
    case "route":
      return { ...turn, route: event };
    case "usage":
      return { ...turn, usage: event };
    case "error":
      return { ...turn, error: event.message };
    case "done":
      return { ...turn, state: "done" };
  }
}

export const textOf = (turn: Extract<Turn, { role: "assistant" }>) =>
  turn.parts
    .filter((p): p is TextPart => p.kind === "text")
    .map((p) => p.text)
    .join("\n\n")
    .trim();

export function AssistantTurn({ turn }: { turn: Extract<Turn, { role: "assistant" }> }) {
  const tools = turn.parts.filter((p): p is ToolStep => p.kind === "tool");
  const text = textOf(turn);
  const waiting = turn.state === "streaming" && !text && tools.every((t) => t.status !== "running");
  // Neutral once answered: the owl never cheers or frowns at what an answer says about the market.
  const mood = turn.error ? "cautious" : turn.state === "streaming" ? "thinking" : "idle";
  return (
    <div className="flex gap-2.5">
      <Mascot size={26} mood={mood} className="mt-0.5" />
      <div className="min-w-0 flex-1 space-y-2">
      {tools.length > 0 && (
        <ol className="space-y-1 rounded-md border bg-card/60 px-2.5 py-2">
          {tools.map((step) => (
            <li key={step.callId} className="flex items-center gap-2 text-[11px] text-muted-foreground" title={step.preview}>
              {step.status === "running" ? (
                <Loader2 className="size-3 shrink-0 animate-spin" />
              ) : step.status === "ok" ? (
                <Check className="size-3 shrink-0 text-up" />
              ) : (
                <AlertTriangle className="size-3 shrink-0 text-down" />
              )}
              <span className="truncate">{toolLabel(step)}</span>
            </li>
          ))}
        </ol>
      )}
      {text && (
        <div className="text-[13px] leading-relaxed [&_code]:num [&_code]:rounded-sm [&_code]:bg-muted [&_code]:px-1 [&_code]:text-[11.5px] [&_h1,&_h2,&_h3]:mt-3 [&_h1,&_h2,&_h3]:mb-1 [&_h1,&_h2,&_h3]:text-[13px] [&_h1,&_h2,&_h3]:font-semibold [&_li]:my-0.5 [&_ol]:list-decimal [&_ol]:pl-4 [&_p]:my-1.5 [&_strong]:font-semibold [&_table]:my-2 [&_table]:text-[11.5px] [&_td]:border-t [&_td]:px-1.5 [&_td]:py-0.5 [&_th]:px-1.5 [&_th]:text-left [&_ul]:list-disc [&_ul]:pl-4">
          <Markdown>{text}</Markdown>
        </div>
      )}
      {waiting && <p className="text-xs text-muted-foreground">Thinking…</p>}
      {turn.error && <p className="rounded-md border border-down/40 bg-down/10 px-2.5 py-1.5 text-xs text-down">{turn.error}</p>}
      {turn.state === "stopped" && <p className="kicker">Stopped</p>}
      </div>
    </div>
  );
}

export function Analyst({ open, onClose, context }: { open: boolean; onClose: () => void; context: DeskContext }) {
  const config = useQuery({ queryKey: ["ai-config"], queryFn: getAiConfig, staleTime: Infinity, enabled: open });
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const abort = useRef<AbortController | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const busy = turns.at(-1)?.role === "assistant" && (turns.at(-1) as Extract<Turn, { role: "assistant" }>).state === "streaming";
  const ready = !!config.data?.enabled;

  useEffect(() => {
    if (open) setTimeout(() => input.current?.focus(), 50);
  }, [open]);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [turns]);

  useEffect(() => () => abort.current?.abort(), []);

  const updateLast = (fn: (turn: Extract<Turn, { role: "assistant" }>) => Extract<Turn, { role: "assistant" }>) =>
    setTurns((all) => {
      const last = all.at(-1);
      if (last?.role !== "assistant") return all;
      return [...all.slice(0, -1), fn(last)];
    });

  async function ask(question: string) {
    const content = question.trim();
    if (!content || busy || !ready) return;
    const history: ChatTurn[] = [];
    for (const turn of turns) {
      if (turn.role === "user") history.push({ role: "user", content: turn.content });
      else if (textOf(turn)) history.push({ role: "assistant", content: textOf(turn) });
    }
    // Keep strict user/assistant alternation for providers that require it.
    if (history.at(-1)?.role === "user") history.pop();
    history.push({ role: "user", content });

    setDraft("");
    setTurns((all) => [...all, { role: "user", content }, { role: "assistant", parts: [], state: "streaming" }]);
    const controller = new AbortController();
    abort.current = controller;
    try {
      await streamChat({ messages: history.slice(-20), snapshot: captureDesk(context) }, (event) => updateLast((turn) => apply(turn, event)), controller.signal);
      updateLast((turn) => (turn.state === "streaming" ? { ...turn, state: "done" } : turn));
    } catch (error) {
      if (controller.signal.aborted) updateLast((turn) => ({ ...turn, state: "stopped" }));
      else updateLast((turn) => ({ ...turn, state: "done", error: error instanceof Error ? error.message : "Request failed" }));
    }
  }

  const stop = () => abort.current?.abort();

  return (
    <aside
      aria-label="Desk analyst"
      aria-hidden={!open}
      className={cn(
        "fixed inset-y-0 right-0 z-40 flex w-[min(460px,100vw)] flex-col border-l bg-popover text-popover-foreground shadow-2xl transition-transform duration-300",
        open ? "translate-x-0" : "pointer-events-none translate-x-full",
      )}
    >
      <header className="rule-double flex items-center gap-2 px-4 py-3">
        <div className="min-w-0 flex-1">
          <h2 className="text-[14px] font-semibold">Desk analyst</h2>
          <p className="kicker truncate">Reads your screen · read-only</p>
        </div>
        <button onClick={() => (stop(), setTurns([]))} disabled={!turns.length} aria-label="New conversation" title="New conversation" className="rounded-md border p-1.5 text-muted-foreground hover:text-foreground disabled:opacity-40">
          <SquarePen className="size-3.5" />
        </button>
        <button onClick={onClose} aria-label="Close analyst" className="rounded-md border p-1.5 text-muted-foreground hover:text-foreground">
          <X className="size-3.5" />
        </button>
      </header>

      {config.isError ? (
        <div className="flex flex-col items-center gap-3 p-8 text-center text-sm text-muted-foreground">
          <Mascot size={72} mood="sleeping" />
          The analyst can't be reached right now.
        </div>
      ) : config.data && !config.data.enabled ? (
        <div className="flex flex-col items-center gap-3 p-8 text-center text-sm text-muted-foreground">
          <Mascot size={72} mood="sleeping" />
          The analyst isn't available right now.
        </div>
      ) : (
        <>
          <div ref={scroller} className="scroll-thin min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-4">
            {turns.length === 0 && (
              <div className="space-y-3">
                <div className="flex items-center gap-3">
                  <Mascot size={56} mood="curious" />
                  <p className="text-[13px] text-muted-foreground">
                    <span className="block font-semibold text-foreground">Hoot. Ask me about {context.symbol}.</span>
                    I read what's on your screen (live price, order flow, book) and can pull candles, indicators, funding, news and movers.
                  </p>
                </div>
                <div className="flex flex-col gap-1.5">
                  {suggestions(context.symbol, context.hasPerp).map((s) => (
                    <button key={s} onClick={() => ask(s)} disabled={!ready} className="rounded-md border bg-card/60 px-3 py-2 text-left text-[12.5px] hover:border-foreground/40 hover:bg-accent">
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {turns.map((turn, i) =>
              turn.role === "user" ? (
                <div key={i} className="ml-8 rounded-lg bg-accent px-3 py-2 text-[13px]">
                  {turn.content}
                </div>
              ) : (
                <AssistantTurn key={i} turn={turn} />
              ),
            )}
          </div>
          <form
            className="border-t p-3"
            onSubmit={(e) => {
              e.preventDefault();
              ask(draft);
            }}
          >
            <div className="flex items-end gap-2 rounded-lg border bg-card px-2.5 py-2 focus-within:border-foreground/40">
              <textarea
                ref={input}
                rows={2}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    ask(draft);
                  }
                }}
                placeholder={`Ask about ${context.symbol}…`}
                className="max-h-40 min-h-[2.5rem] flex-1 resize-none bg-transparent text-[13px] outline-none placeholder:text-muted-foreground/70"
              />
              {busy ? (
                <button type="button" onClick={stop} aria-label="Stop" className="rounded-md bg-foreground p-1.5 text-background">
                  <Square className="size-3.5" />
                </button>
              ) : (
                <button type="submit" disabled={!draft.trim() || !ready} aria-label="Send" className="rounded-md bg-primary p-1.5 text-primary-foreground disabled:opacity-40">
                  <ArrowUp className="size-3.5" />
                </button>
              )}
            </div>
            <p className="kicker mt-1.5 tracking-normal normal-case">
              Not financial advice.
            </p>
          </form>
        </>
      )}
    </aside>
  );
}
