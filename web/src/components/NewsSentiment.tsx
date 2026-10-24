import { RefreshCw, Sparkles } from "lucide-react";
import type { UseQueryResult } from "@tanstack/react-query";
import type { SentimentRead } from "@/lib/news";
import { cn } from "@/lib/utils";
import { Mascot, useMascotOn, type MascotMood } from "./Mascot";

type Tone = "positive" | "negative" | "mixed" | "neutral";

export const TONE: Record<Tone, { text: string; bar: string; tint: string; border: string; label: string }> = {
  positive: { text: "text-positive", bar: "bg-positive", tint: "bg-positive/10", border: "border-positive/40", label: "Positive" },
  negative: { text: "text-negative", bar: "bg-negative", tint: "bg-negative/10", border: "border-negative/40", label: "Negative" },
  mixed: { text: "text-mixed", bar: "bg-mixed", tint: "bg-mixed/12", border: "border-mixed/45", label: "Mixed" },
  neutral: { text: "text-muted-foreground", bar: "bg-muted-foreground/50", tint: "bg-muted/40", border: "border-border", label: "Neutral" },
};

// The owl reflects the news read only; it never reacts to price.
const OWL_MOOD: Record<Tone, MascotMood> = { positive: "happy", negative: "cautious", mixed: "curious", neutral: "idle" };

export const signed = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(2)}`;

/** Overall AI read shown above the selected instrument's headlines; per-headline scores colour the list itself. */
export function SentimentSummary({
  read,
  symbol,
  enabled,
  onReanalyze,
}: {
  read: UseQueryResult<SentimentRead>;
  symbol: string;
  enabled: boolean | undefined;
  onReanalyze: () => void;
}) {
  const owl = useMascotOn();
  if (enabled !== true) return null;
  if (read.isError)
    return (
      <p className="mx-4 mt-2 flex items-center justify-between gap-2 rounded-md border px-2.5 py-1.5 text-[11px] text-muted-foreground">
        AI read failed: {read.error.message}
        <button onClick={onReanalyze} title="Try again" className="rounded-sm border p-0.5 hover:text-foreground">
          <RefreshCw className="size-3" />
        </button>
      </p>
    );
  if (read.isPending || read.isFetching)
    return (
      <div className="mx-4 mt-2 flex items-center gap-2 rounded-md border border-dashed px-2.5 py-2 text-[11px] text-muted-foreground" aria-busy>
        {owl ? <Mascot size={26} mood="thinking" className="-my-1" /> : <Sparkles className="size-3.5 animate-pulse text-chart-1" />}
        Reading the latest {symbol} headlines…
      </div>
    );

  const data = read.data;
  if (!data.overall) return null;
  const tone = TONE[data.overall.label];
  const counts = { positive: 0, negative: 0, neutral: 0 };
  data.items.forEach((item) => counts[item.label]++);

  return (
    <section className={cn("mx-4 mt-2 rounded-lg border px-3 py-2", tone.tint, tone.border)} aria-label="AI read of the latest headlines">
      <div className="flex items-baseline gap-2">
        {owl ? <Mascot size={26} mood={OWL_MOOD[data.overall.label]} className="-my-1 self-center" /> : <Sparkles className={cn("size-3 self-center", tone.text)} />}
        <span className={cn("text-[13px] font-semibold", tone.text)}>{tone.label}</span>
        <span className={cn("num text-[12px]", tone.text)}>{signed(data.overall.score)}</span>
        <span className="kicker ml-auto tracking-normal normal-case">
          {counts.positive} pos · {counts.negative} neg · {counts.neutral} neutral
        </span>
        <button onClick={onReanalyze} title="Run the analysis again now" aria-label="Re-analyse headlines" className="self-center rounded-sm border p-0.5 text-muted-foreground hover:text-foreground">
          <RefreshCw className="size-3" />
        </button>
      </div>
      {/* -1 … +1 gauge */}
      <div className="relative mt-1.5 h-1 rounded-full bg-gradient-to-r from-negative/50 via-muted to-positive/50">
        <span
          className={cn("absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-background", tone.bar)}
          style={{ left: `${((data.overall.score + 1) / 2) * 100}%` }}
        />
      </div>
      <p className="mt-1.5 line-clamp-3 text-[11.5px] leading-snug" title={data.overall.summary}>
        {data.overall.summary}
      </p>
    </section>
  );
}
