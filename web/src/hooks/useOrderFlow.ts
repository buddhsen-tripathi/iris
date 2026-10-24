import { useEffect, useMemo, useState } from "react";
import { largeTradeThreshold, shareSeries, summarize, type Print } from "@/lib/flow";
import { RETAIN_MS, hyperliquidTrades } from "@/lib/hyperliquid";

const EMPTY: Print[] = [];

/**
 * Live taker flow for a Hyperliquid coin over a trailing window, recomputed once a second so a
 * busy tape doesn't re-render on every print.
 */
export function useOrderFlow(coin: string | undefined, windowMs: number) {
  const [tick, setTick] = useState(() => ({ now: Date.now(), version: -1 }));
  useEffect(() => {
    if (!coin) return;
    let dirty = true;
    const unsubscribe = hyperliquidTrades.subscribe(coin, () => (dirty = true));
    const id = setInterval(() => {
      if (!dirty) return setTick((t) => ({ ...t, now: Date.now() }));
      dirty = false;
      setTick({ now: Date.now(), version: hyperliquidTrades.snapshot(coin)?.version ?? 0 });
    }, 1000);
    return () => {
      clearInterval(id);
      unsubscribe();
    };
  }, [coin]);

  return useMemo(() => {
    const entry = coin ? hyperliquidTrades.snapshot(coin) : undefined;
    const log = entry?.log ?? EMPTY;
    const now = tick.now;
    const since = entry?.since ?? now;
    const from = now - windowMs;
    const current = summarize(log, from, now);
    const previous = summarize(log, from - windowMs, from);
    const step = Math.max(1000, windowMs / 60);
    return {
      current,
      previous: from - windowMs >= since ? previous : undefined,
      series: shareSeries(log, windowMs, step, Math.max(since, now - RETAIN_MS), now),
      recent: log.slice(-40).reverse(),
      largeAt: largeTradeThreshold(log, from),
      since,
      // Until the feed has been open for a full window, totals cover less than the window.
      covered: Math.min(1, (now - since) / windowMs),
      now,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [coin, windowMs, tick]);
}
