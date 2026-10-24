import { ArrowUp, MousePointerClick, Square, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { streamChat, type ChatTurn, type Focus } from "@/lib/ai";
import { captureDesk } from "@/lib/desk";
import { describe, pickElement } from "@/lib/focus";
import { cn } from "@/lib/utils";
import { AssistantTurn, apply, textOf, type DeskContext, type Turn } from "./Analyst";
import { Mascot, useMascotOn } from "./Mascot";

type Rect = { top: number; left: number; width: number; height: number };
const POPOVER_W = 380;
const rectOf = (el: Element): Rect => {
  const r = el.getBoundingClientRect();
  return { top: r.top, left: r.left, width: r.width, height: r.height };
};

/** Outline drawn over an element without touching its layout. */
function Outline({ rect, solid }: { rect: Rect | null; solid?: boolean }) {
  if (!rect) return null;
  return (
    <div
      aria-hidden
      data-ask-ignore
      className={cn(
        "pointer-events-none fixed z-[60] rounded-[3px] transition-all duration-75",
        solid ? "bg-chart-1/8 outline-2 outline-chart-1" : "bg-chart-1/10 outline-2 outline-dashed outline-chart-1/80",
      )}
      style={{ top: rect.top - 2, left: rect.left - 2, width: rect.width + 4, height: rect.height + 4 }}
    />
  );
}

const POPOVER_H = 420;
const GAP = 12;

/** Beside the element (right, else left) so it stays visible; over the click point only when it's too wide for either. */
export function placePopover(rect: Rect, click: { x: number; y: number }, vw = window.innerWidth, vh = window.innerHeight) {
  const clampTop = (top: number) => Math.max(8, Math.min(top, vh - POPOVER_H - 8));
  if (rect.left + rect.width + GAP + POPOVER_W <= vw - 8) return { left: rect.left + rect.width + GAP, top: clampTop(rect.top) };
  if (rect.left - GAP - POPOVER_W >= 8) return { left: rect.left - GAP - POPOVER_W, top: clampTop(rect.top) };
  return { left: Math.max(8, Math.min(click.x + 14, vw - POPOVER_W - 8)), top: clampTop(click.y + 14) };
}

const SUGGESTIONS = ["What does this mean?", "Is this good or bad for the price?", "What should I watch here?"];

/**
 * Point & ask: pick any element (picker mode, or ⌥-click anywhere) and ask Haiku about it.
 * The element's text and panel go to the server as quoted data alongside the live desk snapshot.
 */
export function PointAndAsk({ picking, onPickingChange, context }: { picking: boolean; onPickingChange: (on: boolean) => void; context: DeskContext }) {
  const [hover, setHover] = useState<Rect | null>(null);
  const [target, setTarget] = useState<{ el: HTMLElement; focus: Focus; at: { x: number; y: number } } | null>(null);
  const [outline, setOutline] = useState<Rect | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const abort = useRef<AbortController | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const owl = useMascotOn();
  const last = turns.at(-1);
  const busy = last?.role === "assistant" && last.state === "streaming";

  const close = useCallback(() => {
    abort.current?.abort();
    setTarget(null);
    setTurns([]);
    setDraft("");
  }, []);

  const select = useCallback(
    (el: HTMLElement, x: number, y: number) => {
      abort.current?.abort();
      setTurns([]);
      setDraft("");
      setTarget({ el, focus: describe(el), at: { x, y } });
      onPickingChange(false);
      setHover(null);
    },
    [onPickingChange],
  );

  // Picker mode: highlight under the pointer; the click selects instead of activating the element.
  useEffect(() => {
    if (!picking) return;
    const onMove = (event: MouseEvent) => {
      const el = pickElement(event.target);
      setHover(el ? rectOf(el) : null);
    };
    const onClick = (event: MouseEvent) => {
      const el = pickElement(event.target);
      if (!el) return;
      event.preventDefault();
      event.stopPropagation();
      select(el, event.clientX, event.clientY);
    };
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onPickingChange(false);
    document.addEventListener("mousemove", onMove, true);
    document.addEventListener("click", onClick, true);
    document.addEventListener("keydown", onKey, true);
    document.documentElement.style.cursor = "crosshair";
    return () => {
      document.removeEventListener("mousemove", onMove, true);
      document.removeEventListener("click", onClick, true);
      document.removeEventListener("keydown", onKey, true);
      document.documentElement.style.cursor = "";
      setHover(null);
    };
  }, [picking, onPickingChange, select]);

  // ⌥-click asks about anything without entering picker mode.
  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (!event.altKey) return;
      const el = pickElement(event.target);
      if (!el) return;
      event.preventDefault();
      event.stopPropagation();
      select(el, event.clientX, event.clientY);
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [select]);

  // Keep the selection outlined as the page scrolls, resizes or re-renders.
  useEffect(() => {
    if (!target) return setOutline(null);
    let frame = 0;
    const tick = () => {
      setOutline((previous) => {
        if (!target.el.isConnected) return null;
        const next = rectOf(target.el);
        return previous && previous.top === next.top && previous.left === next.left && previous.width === next.width && previous.height === next.height ? previous : next;
      });
      frame = requestAnimationFrame(tick);
    };
    tick();
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && close();
    const onDown = (event: MouseEvent) => {
      if (!event.altKey && !(event.target instanceof Element && event.target.closest("[data-ask-ignore]"))) close();
    };
    window.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown, true);
    setTimeout(() => input.current?.focus(), 30);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown, true);
    };
  }, [target, close]);

  useLayoutEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [turns]);

  useEffect(() => () => abort.current?.abort(), []);

  async function ask(question: string) {
    const content = question.trim();
    if (!content || busy || !target) return;
    const history: ChatTurn[] = [];
    for (const turn of turns) {
      if (turn.role === "user") history.push({ role: "user", content: turn.content });
      else if (textOf(turn)) history.push({ role: "assistant", content: textOf(turn) });
    }
    if (history.at(-1)?.role === "user") history.pop();
    history.push({ role: "user", content });
    setDraft("");
    setTurns((all) => [...all, { role: "user", content }, { role: "assistant", parts: [], state: "streaming" }]);
    const update = (fn: (turn: Extract<Turn, { role: "assistant" }>) => Extract<Turn, { role: "assistant" }>) =>
      setTurns((all) => {
        const tail = all.at(-1);
        return tail?.role === "assistant" ? [...all.slice(0, -1), fn(tail)] : all;
      });
    const controller = new AbortController();
    abort.current = controller;
    // Re-read the element so follow-ups see its current numbers.
    const focus = target.el.isConnected ? describe(target.el) : target.focus;
    try {
      await streamChat({ messages: history.slice(-12), snapshot: captureDesk(context), focus }, (event) => update((turn) => apply(turn, event)), controller.signal);
      update((turn) => (turn.state === "streaming" ? { ...turn, state: "done" } : turn));
    } catch (error) {
      if (controller.signal.aborted) update((turn) => ({ ...turn, state: "stopped" }));
      else update((turn) => ({ ...turn, state: "done", error: error instanceof Error ? error.message : "Request failed" }));
    }
  }

  const position = target && placePopover(outline ?? rectOf(target.el), target.at);

  return (
    <>
      {picking && <Outline rect={hover} />}
      {picking && (
        <div data-ask-ignore className="fixed bottom-10 left-1/2 z-[60] flex -translate-x-1/2 items-center gap-2 rounded-full border bg-popover px-3 py-1.5 text-xs shadow-lg">
          {owl ? <Mascot size={24} mood="curious" className="-my-1" /> : <MousePointerClick className="size-3.5 text-chart-1" />}
          Click anything to ask about it · <kbd className="num rounded-sm border px-1 text-[10px]">Esc</kbd> to cancel
        </div>
      )}
      {target && <Outline rect={outline} solid />}
      {target && position && (
        <div
          data-ask-ignore
          role="dialog"
          aria-label="Ask about the selected element"
          className="fixed z-[61] flex max-h-[420px] flex-col overflow-hidden rounded-lg border bg-popover text-popover-foreground shadow-2xl"
          style={{ ...position, width: POPOVER_W }}
        >
          <header className="flex items-start gap-2 border-b px-3 py-2">
            <div className="min-w-0 flex-1">
              <p className="kicker flex items-center gap-1.5">
                <MousePointerClick className="size-3 text-chart-1" />
                {target.focus.panel}
              </p>
              <p className="mt-0.5 line-clamp-2 text-[12px] text-muted-foreground" title={target.focus.text}>
                “{target.focus.text}”
              </p>
            </div>
            <button onClick={close} aria-label="Close" className="rounded-sm p-0.5 text-muted-foreground hover:text-foreground">
              <X className="size-3.5" />
            </button>
          </header>
          <div ref={scroller} className="scroll-thin min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-2.5">
            {turns.length === 0 && (
              <div className="flex flex-wrap gap-1.5">
                {SUGGESTIONS.map((s) => (
                  <button key={s} onClick={() => ask(s)} className="rounded-full border bg-card/70 px-2.5 py-1 text-[11.5px] hover:border-foreground/40 hover:bg-accent">
                    {s}
                  </button>
                ))}
              </div>
            )}
            {turns.map((turn, i) =>
              turn.role === "user" ? (
                <div key={i} className="ml-6 rounded-md bg-accent px-2.5 py-1.5 text-[12.5px]">
                  {turn.content}
                </div>
              ) : (
                <AssistantTurn key={i} turn={turn} />
              ),
            )}
          </div>
          <form
            className="border-t p-2"
            onSubmit={(e) => {
              e.preventDefault();
              ask(draft);
            }}
          >
            <div className="flex items-end gap-2 rounded-md border bg-card px-2 py-1.5 focus-within:border-foreground/40">
              <textarea
                ref={input}
                rows={1}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    ask(draft);
                  }
                }}
                placeholder="Ask about this…"
                className="max-h-24 min-h-[1.5rem] flex-1 resize-none bg-transparent text-[12.5px] outline-none placeholder:text-muted-foreground/70"
              />
              {busy ? (
                <button type="button" onClick={() => abort.current?.abort()} aria-label="Stop" className="rounded-sm bg-foreground p-1 text-background">
                  <Square className="size-3" />
                </button>
              ) : (
                <button type="submit" disabled={!draft.trim()} aria-label="Ask" className="rounded-sm bg-primary p-1 text-primary-foreground disabled:opacity-40">
                  <ArrowUp className="size-3" />
                </button>
              )}
            </div>
          </form>
        </div>
      )}
    </>
  );
}
