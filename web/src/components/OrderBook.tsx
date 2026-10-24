import { useElapsed, useNow, useTopic } from "@/hooks/useMarket";
import { age, decimalsFor, price, size } from "@/lib/format";
import { topics, type BookLevel, type OrderBook as Book } from "@/lib/tm";
import { cn } from "@/lib/utils";
import { Empty, Panel } from "./ui";

const DEPTH = 6;

type Row = { px: number; sz: number; total: number; n: number };

function accumulate(levels: BookLevel[]): Row[] {
  let total = 0;
  return levels.slice(0, DEPTH).map((level) => {
    const sz = Number(level.sz);
    total += sz;
    return { px: Number(level.px), sz, total, n: level.n };
  });
}

function Side({ rows, max, side, decimals }: { rows: Row[]; max: number; side: "bid" | "ask"; decimals: number }) {
  return (
    <ul className="num text-[11px]">
      {rows.map((row) => (
        <li key={row.px} className="relative grid grid-cols-[1fr_1fr_1fr] px-4 py-[2px]" title={`${row.n} orders`}>
          <span
            aria-hidden
            className={cn("absolute inset-y-px right-0 transition-[width] duration-500", side === "bid" ? "bg-up/10" : "bg-down/15")}
            style={{ width: `${(row.total / max) * 100}%` }}
          />
          <span className={cn("relative", side === "bid" ? "text-up" : "text-down")}>{price(row.px, decimals)}</span>
          <span className="relative text-right">{size(row.sz)}</span>
          <span className="relative text-right text-muted-foreground">{size(row.total)}</span>
        </li>
      ))}
    </ul>
  );
}

export function OrderBook({ symbol, hasPerp }: { symbol: string; hasPerp: boolean }) {
  const topic = hasPerp ? topics.perpBook(symbol) : null;
  const { value, rejected } = useTopic<Book>(topic);
  const now = useNow();
  const silent = useElapsed(symbol);
  const book = value?.data;
  const bids = book ? accumulate(book.bids) : [];
  const asks = book ? accumulate(book.asks) : [];
  const max = Math.max(bids.at(-1)?.total ?? 0, asks.at(-1)?.total ?? 0) || 1;
  const bestBid = bids[0]?.px;
  const bestAsk = asks[0]?.px;
  const mid = bestBid && bestAsk ? (bestBid + bestAsk) / 2 : undefined;
  const spreadBps = bestBid && bestAsk ? ((bestAsk - bestBid) / mid!) * 10_000 : undefined;
  const decimals = decimalsFor(mid ?? 0);

  return (
    <Panel
      title="Order book"
      meta={book ? `Perp · ${age(Date.parse(book.event_timestamp), now)} ago` : hasPerp ? "Perp" : undefined}
      delay={160}
    >
      {!hasPerp ? (
        <Empty>{symbol} has no perp listing, so there is no live order book.</Empty>
      ) : rejected ? (
        <Empty>Order book unavailable for {symbol} ({rejected.replaceAll("_", " ")}).</Empty>
      ) : !book ? (
        <Empty>{silent ? `No book has arrived for ${symbol}-USD yet.` : "Waiting for the first book…"}</Empty>
      ) : (
        <div className="flex flex-col py-1">
          <div className="kicker grid grid-cols-3 px-4 py-1.5">
            <span>Price</span>
            <span className="text-right">Size</span>
            <span className="text-right">Total</span>
          </div>
          <Side rows={[...asks].reverse()} max={max} side="ask" decimals={decimals} />
          <div className="my-1 flex items-baseline justify-between border-y bg-accent/50 px-4 py-1.5">
            <span className="num text-base leading-none font-semibold">{price(mid, decimals)}</span>
            <span className="num text-[11px] text-muted-foreground">
              spread {price(bestAsk! - bestBid!, decimals)} · {spreadBps?.toFixed(2)} bps
            </span>
          </div>
          <Side rows={bids} max={max} side="bid" decimals={decimals} />
        </div>
      )}
    </Panel>
  );
}
