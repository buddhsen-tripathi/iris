import { BaselineSeries, ColorType, createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { useTopic } from "@/hooks/useMarket";
import { useOrderFlow } from "@/hooks/useOrderFlow";
import { useTheme } from "@/hooks/useTheme";
import { cssVar } from "@/lib/color";
import type { Print } from "@/lib/flow";
import { age, compact, price, size } from "@/lib/format";
import { topics, type OrderBook } from "@/lib/tm";
import { cn } from "@/lib/utils";
import { Segmented } from "./ui";

const WINDOWS = [
  { id: "1m", label: "1m", ms: 60_000 },
  { id: "5m", label: "5m", ms: 5 * 60_000 },
  { id: "15m", label: "15m", ms: 15 * 60_000 },
] as const;
type WindowId = (typeof WINDOWS)[number]["id"];
// Below this many trades in the window, a lopsided share says little.
const THIN = 20;

/** Buy share over time, drawn like a prediction market's odds line around a 50% baseline. */
function ShareChart({ points }: { points: { time: number; value: number }[] }) {
  const container = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Baseline"> | null>(null);
  const { theme } = useTheme();

  useEffect(() => {
    if (!container.current) return;
    const instance = createChart(container.current, {
      autoSize: true,
      handleScroll: false,
      handleScale: false,
      timeScale: { timeVisible: true, secondsVisible: true, borderVisible: false, rightOffset: 2 },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.08 } },
      crosshair: { horzLine: { visible: false, labelVisible: false } },
      layout: { attributionLogo: false },
    });
    series.current = instance.addSeries(BaselineSeries, {
      baseValue: { type: "price", price: 50 },
      lineWidth: 2,
      priceLineVisible: false,
      priceFormat: { type: "custom", minMove: 0.1, formatter: (v: number) => `${v.toFixed(0)}%` },
      autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }),
    });
    chart.current = instance;
    return () => {
      instance.remove();
      chart.current = series.current = null;
    };
  }, []);

  useEffect(() => {
    const grid = cssVar("--border", 0.5);
    chart.current?.applyOptions({
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: cssVar("--muted-foreground"), fontFamily: "Geist Mono Variable, monospace", fontSize: 10 },
      grid: { vertLines: { visible: false }, horzLines: { color: grid } },
    });
    series.current?.applyOptions({
      topLineColor: cssVar("--up"),
      topFillColor1: cssVar("--up", 0.22),
      topFillColor2: cssVar("--up", 0.02),
      bottomLineColor: cssVar("--down"),
      bottomFillColor1: cssVar("--down", 0.02),
      bottomFillColor2: cssVar("--down", 0.25),
    });
  }, [theme]);

  useEffect(() => {
    series.current?.setData(points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
    chart.current?.timeScale().fitContent();
  }, [points]);

  return <div ref={container} className="h-full w-full" />;
}

function Outcome({
  side,
  share,
  notional,
  amount,
  base,
  count,
  active,
  onClick,
}: {
  side: "buy" | "sell";
  share: number | undefined;
  notional: number;
  amount: number;
  base: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  const tone = side === "buy" ? "up" : "down";
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      title={`Show only ${side === "buy" ? "buyer" : "seller"}-initiated trades`}
      className={cn(
        "relative flex-1 overflow-hidden rounded-lg border px-3 py-2 text-left transition-colors",
        tone === "up" ? "border-up/30 hover:border-up/70" : "border-down/40 hover:border-down/80",
        active && (tone === "up" ? "border-up ring-1 ring-up/40" : "border-down ring-1 ring-down/40"),
      )}
    >
      <span
        aria-hidden
        className={cn("absolute inset-y-0 left-0 transition-[width] duration-700", tone === "up" ? "bg-up/10" : "bg-down/12")}
        style={{ width: `${share ?? 0}%` }}
      />
      <span className="relative flex items-baseline justify-between gap-2">
        <span className={cn("text-[13px] font-semibold", tone === "up" ? "text-up" : "text-down")}>{side === "buy" ? "Buyers" : "Sellers"}</span>
        <span className={cn("text-xl font-semibold tabular-nums", tone === "up" ? "text-up" : "text-down")}>{share === undefined ? "—" : `${share.toFixed(0)}%`}</span>
      </span>
      <span className="num relative mt-0.5 block text-[10.5px] text-muted-foreground">
        {compact(notional, "$")} · {size(amount)} {base} · {count} trades
      </span>
    </button>
  );
}

function Activity({ prints, base, largeAt, now, filter }: { prints: Print[]; base: string; largeAt: number; now: number; filter: "buy" | "sell" | null }) {
  const rows = filter ? prints.filter((p) => p.side === filter) : prints;
  return (
    <ol className="scroll-thin min-h-0 flex-1 overflow-y-auto">
      {rows.map((p) => {
        const large = p.notional >= largeAt;
        return (
          <li
            key={p.tid}
            className={cn(
              "num grid grid-cols-[3.25rem_1fr_auto_2.25rem] items-baseline gap-2 border-b border-border/40 px-4 py-[5px] text-[11px]",
              large && "bg-accent font-semibold",
            )}
          >
            <span className={cn("font-sans text-[11px] font-semibold", p.side === "buy" ? "text-up" : "text-down")}>
              {p.side === "buy" ? "▲ Buy" : "▼ Sell"}
            </span>
            <span className="truncate">
              {size(p.sz)} {base} <span className="text-muted-foreground">@ {price(p.px)}</span>
            </span>
            <span className={cn(large && (p.side === "buy" ? "text-up" : "text-down"))}>{compact(p.notional, "$")}</span>
            <span className="text-right text-muted-foreground">{age(p.time, now)}</span>
          </li>
        );
      })}
      {rows.length === 0 && <li className="px-4 py-6 text-center text-xs text-muted-foreground">Waiting for trades…</li>}
    </ol>
  );
}

export function OrderFlow({ symbol, hasPerp }: { symbol: string; hasPerp: boolean }) {
  const [windowId, setWindowId] = useState<WindowId>("5m");
  const [filter, setFilter] = useState<"buy" | "sell" | null>(null);
  const span = WINDOWS.find((w) => w.id === windowId)!;
  // The order-book stream names the exact Hyperliquid coin, including stock perps like "xyz:NVDA".
  const coin = useTopic<OrderBook>(hasPerp ? topics.perpBook(symbol) : null).value?.data.coin;
  const flow = useOrderFlow(coin, span.ms);
  const { current, previous } = flow;
  const base = symbol;
  const shift = current.share !== undefined && previous?.share !== undefined ? current.share - previous.share : undefined;
  const leader = current.share === undefined ? undefined : current.share >= 50 ? "buy" : "sell";
  const leadShare = current.share === undefined ? undefined : leader === "buy" ? current.share : 100 - current.share;
  const trades = current.buyCount + current.sellCount;

  useEffect(() => setFilter(null), [symbol]);

  if (!hasPerp) {
    return (
      <div className="flex h-full items-center justify-center px-6 text-center text-xs text-muted-foreground">
        Live buy/sell flow is available for perp-listed instruments, and {symbol} has no perp listing. Try BTC, ETH, SOL, HYPE or NVDA.
      </div>
    );
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-1 md:grid-cols-[minmax(0,1fr)_minmax(280px,38%)]">
      <div className="flex min-h-0 flex-col gap-2 px-5 py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <h3 className="truncate text-[15px] font-semibold" title={`${symbol} perp taker volume`}>Who's in control of {symbol}, last {span.label}?</h3>
          </div>
          <Segmented label="Flow window" options={WINDOWS.map((w) => ({ id: w.id, label: w.label }))} value={windowId} onChange={setWindowId} />
        </div>
        <div className="flex items-baseline gap-3">
          <span
            className={cn(
              "text-[2rem] leading-none font-semibold tabular-nums",
              leader === "buy" ? "text-up" : leader === "sell" && "text-down",
              trades < THIN && "opacity-60",
            )}
          >
            {leadShare === undefined ? "—" : `${leadShare.toFixed(0)}%`}
          </span>
          <span className="text-sm text-muted-foreground">{leader === undefined ? "no trades yet" : leader === "buy" ? "buyers" : "sellers"}</span>
          {shift !== undefined && (
            <span className={cn("num text-[11px]", shift > 0 ? "text-up" : shift < 0 ? "text-down" : "text-muted-foreground")} title={`Buy share vs the previous ${span.label}`}>
              {shift > 0 ? "▲" : shift < 0 ? "▼" : ""} {Math.abs(shift).toFixed(1)} pts buy share vs prior {span.label}
            </span>
          )}
          <span className="kicker ml-auto tracking-normal normal-case" title="Share of aggressive (taker) volume by notional. It describes recent flow; it is not a probability.">
            {flow.covered < 1
              ? `collecting · ${Math.round(flow.covered * 100)}% of window`
              : trades < THIN
                ? `thin tape · only ${trades} trades`
                : "share of taker notional, not a forecast"}
          </span>
        </div>
        <div className="min-h-[90px] flex-1">
          <ShareChart points={flow.series} />
        </div>
        <div className="flex gap-2">
          <Outcome
            side="buy"
            share={current.share}
            notional={current.buyNotional}
            amount={current.buySize}
            base={base}
            count={current.buyCount}
            active={filter === "buy"}
            onClick={() => setFilter((f) => (f === "buy" ? null : "buy"))}
          />
          <Outcome
            side="sell"
            share={current.share === undefined ? undefined : 100 - current.share}
            notional={current.sellNotional}
            amount={current.sellSize}
            base={base}
            count={current.sellCount}
            active={filter === "sell"}
            onClick={() => setFilter((f) => (f === "sell" ? null : "sell"))}
          />
        </div>
      </div>
      <div className="flex min-h-0 flex-col border-l max-md:border-t max-md:border-l-0">
        <div className="flex items-baseline justify-between px-4 pt-3 pb-2">
          <span className="text-[13px] font-semibold">Activity</span>
          <span className="kicker flex items-center gap-1.5">
            <span className="live-dot size-1.5 rounded-full bg-chart-1" />
            {filter ? `${filter}s only` : "live trades"} · large ≥ {compact(flow.largeAt, "$")}
          </span>
        </div>
        <Activity prints={flow.recent} base={base} largeAt={flow.largeAt} now={flow.now} filter={filter} />
      </div>
    </div>
  );
}
