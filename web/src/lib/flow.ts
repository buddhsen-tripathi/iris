// Taker buy/sell flow from individual trades. A "buy" print is a trade whose aggressor lifted the ask.

export type Print = { tid: number; time: number; side: "buy" | "sell"; px: number; sz: number; notional: number };
export type HlTrade = { coin: string; side: "B" | "A"; px: string; sz: string; time: number; tid: number };

export function toPrint(trade: HlTrade): Print | null {
  const px = Number(trade.px);
  const sz = Number(trade.sz);
  if (!(px > 0) || !(sz > 0) || !Number.isFinite(trade.time) || (trade.side !== "B" && trade.side !== "A")) return null;
  return { tid: trade.tid, time: trade.time, side: trade.side === "B" ? "buy" : "sell", px, sz, notional: px * sz };
}

/** Adds prints to a time-ordered log, skipping repeats and dropping anything older than `retainFrom`. */
export function insertPrints(log: Print[], incoming: Print[], retainFrom: number): Print[] {
  const seen = new Set(log.map((p) => p.tid));
  const fresh = incoming.filter((p) => !seen.has(p.tid) && p.time >= retainFrom);
  if (!fresh.length && (!log.length || log[0].time >= retainFrom)) return log;
  return [...log, ...fresh].filter((p) => p.time >= retainFrom).sort((a, b) => a.time - b.time || a.tid - b.tid);
}

type FlowSummary = {
  buyNotional: number;
  sellNotional: number;
  buySize: number;
  sellSize: number;
  buyCount: number;
  sellCount: number;
  /** Buy share of taker notional, 0–100; undefined with no trades. */
  share: number | undefined;
  largest: Print | undefined;
};

/** Totals for prints with from < time ≤ to. */
export function summarize(log: Print[], from: number, to: number): FlowSummary {
  const s: FlowSummary = { buyNotional: 0, sellNotional: 0, buySize: 0, sellSize: 0, buyCount: 0, sellCount: 0, share: undefined, largest: undefined };
  for (let i = lowerBound(log, from + 1); i < log.length && log[i].time <= to; i++) {
    const p = log[i];
    if (p.side === "buy") {
      s.buyNotional += p.notional;
      s.buySize += p.sz;
      s.buyCount++;
    } else {
      s.sellNotional += p.notional;
      s.sellSize += p.sz;
      s.sellCount++;
    }
    if (!s.largest || p.notional > s.largest.notional) s.largest = p;
  }
  const total = s.buyNotional + s.sellNotional;
  s.share = total > 0 ? (s.buyNotional / total) * 100 : undefined;
  return s;
}

/** First index whose time is ≥ t. */
function lowerBound(log: Print[], t: number): number {
  let lo = 0;
  let hi = log.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (log[mid].time < t) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/**
 * Rolling buy share sampled every `stepMs` between `start` and `end`, each point covering the
 * trailing `windowMs`. Steps with no trades in their window are skipped. Uses prefix sums, so it
 * stays cheap for long logs.
 */
export function shareSeries(log: Print[], windowMs: number, stepMs: number, start: number, end: number): { time: number; value: number }[] {
  const buy = [0];
  const all = [0];
  for (const p of log) {
    buy.push(buy[buy.length - 1] + (p.side === "buy" ? p.notional : 0));
    all.push(all[all.length - 1] + p.notional);
  }
  const upTo = (t: number) => {
    // Number of prints with time ≤ t.
    let lo = 0;
    let hi = log.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (log[mid].time <= t) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  };
  const points: { time: number; value: number }[] = [];
  const first = Math.ceil(start / stepMs) * stepMs;
  for (let t = first; t <= end; t += stepMs) {
    const hi = upTo(t);
    const lo = upTo(t - windowMs);
    const total = all[hi] - all[lo];
    if (total > 0) points.push({ time: t / 1000, value: ((buy[hi] - buy[lo]) / total) * 100 });
  }
  return points;
}

/** Notional above which a print counts as large: the window's 95th percentile, at least `floor`. */
export function largeTradeThreshold(log: Print[], from: number, floor = 10_000): number {
  const sizes = log.filter((p) => p.time > from).map((p) => p.notional).sort((a, b) => a - b);
  if (!sizes.length) return floor;
  return Math.max(floor, sizes[Math.floor(sizes.length * 0.95)]);
}
