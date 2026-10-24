import type { DeskSnapshot } from "../../server/ai";
import { summarize } from "./flow";
import { hyperliquidTrades } from "./hyperliquid";
import { marketSocket } from "./socket";
import { topics, type LivePrice, type OrderBook, type ProductClass, type ReferencePrice } from "./tm";

const FLOW_WINDOWS = [
  ["1m", 60_000],
  ["5m", 5 * 60_000],
  ["15m", 15 * 60_000],
] as const;

/** Reads the live stores at send time, so the analyst sees exactly what's on screen. */
export function captureDesk(input: {
  symbol: string;
  name?: string;
  productClass: ProductClass;
  assetClass: "crypto" | "stock";
  chartTimeframe: string;
  hasPerp: boolean;
}): DeskSnapshot {
  const now = Date.now();
  const live = marketSocket.snapshot<LivePrice>(topics.price(input.symbol, input.productClass))?.data;
  const book = input.hasPerp ? marketSocket.snapshot<OrderBook>(topics.perpBook(input.symbol))?.data : undefined;
  const ref = marketSocket.snapshot<ReferencePrice>(topics.reference(input.symbol))?.data;
  const flow = book ? hyperliquidTrades.snapshot(book.coin) : undefined;
  const num = (v: string | undefined) => (v === undefined || !Number.isFinite(Number(v)) ? null : Number(v));

  const bestBid = num(book?.bids[0]?.px);
  const bestAsk = num(book?.asks[0]?.px);
  return {
    symbol: input.symbol,
    name: input.name,
    productClass: input.productClass,
    assetClass: input.assetClass,
    chartTimeframe: input.chartTimeframe,
    capturedAt: new Date(now).toISOString(),
    livePrice: live && num(live.price) !== null ? { price: Number(live.price), change1hPct: num(live.change_1h), change24hPct: num(live.change_24h), at: live.timestamp } : null,
    orderFlow:
      book && flow
        ? {
            venue: "hyperliquid-perp",
            coin: book.coin,
            windows: FLOW_WINDOWS.map(([window, ms]) => {
              const s = summarize(flow.log, now - ms, now);
              return {
                window,
                buyShare: s.share === undefined ? null : Math.round(s.share * 10) / 10,
                buyNotional: Math.round(s.buyNotional),
                sellNotional: Math.round(s.sellNotional),
                trades: s.buyCount + s.sellCount,
                coveredFraction: Math.round(Math.min(1, (now - flow.since) / ms) * 100) / 100,
              };
            }),
          }
        : null,
    orderBook:
      book && bestBid !== null && bestAsk !== null
        ? {
            venue: book.venue,
            bestBid,
            bestAsk,
            spreadBps: Math.round(((bestAsk - bestBid) / ((bestAsk + bestBid) / 2)) * 10_000 * 100) / 100,
            bidDepth: book.bids.reduce((a, l) => a + Number(l.sz), 0),
            askDepth: book.asks.reduce((a, l) => a + Number(l.sz), 0),
            levels: Math.min(book.bids.length, book.asks.length),
            at: book.event_timestamp,
          }
        : null,
    reference:
      ref && num(ref.mid_price) !== null
        ? {
            bid: Number(ref.bid),
            mid: Number(ref.mid_price),
            ask: Number(ref.ask),
            sources: ref.sources.map((s) => ({ source: s.source, mid: Number(s.mid_price), weightPct: Number(s.weight_pct) <= 1 ? Number(s.weight_pct) * 100 : Number(s.weight_pct) })),
          }
        : null,
  };
}
