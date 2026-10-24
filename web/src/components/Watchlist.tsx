import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTopic } from "@/hooks/useMarket";
import type { Catalog } from "@/hooks/useCatalog";
import { price } from "@/lib/format";
import { topics, type LivePrice, type ProductClass } from "@/lib/tm";
import { cn } from "@/lib/utils";
import { AssetIcon, Delta, Empty, Panel } from "./ui";

/** Live price for a symbol plus a flash direction that changes on every tick. */
function useTicker(symbol: string, cls: ProductClass) {
  const live = useTopic<LivePrice>(topics.price(symbol, cls)).value?.data;
  const previous = useRef<number | undefined>(undefined);
  const [flash, setFlash] = useState<{ dir: "up" | "down"; n: number } | null>(null);
  useEffect(() => {
    const next = Number(live?.price);
    if (!Number.isFinite(next)) return;
    const before = previous.current;
    previous.current = next;
    if (before !== undefined && next !== before) setFlash((f) => ({ dir: next > before ? "up" : "down", n: (f?.n ?? 0) + 1 }));
  }, [live?.price]);
  return { live, flash };
}

function Row({
  symbol,
  active,
  catalog,
  onSelect,
  onRemove,
}: {
  symbol: string;
  active: boolean;
  catalog: Catalog;
  onSelect: () => void;
  onRemove: () => void;
}) {
  const { live, flash } = useTicker(symbol, catalog.classOf(symbol));
  const asset = catalog.bySymbol.get(symbol);
  return (
    <li className="group relative">
      <button
        onClick={onSelect}
        className={cn(
          "grid w-full grid-cols-[auto_1fr_auto] items-center gap-x-2.5 border-l-2 px-4 py-2 text-left transition-colors",
          active ? "border-chart-1 bg-accent" : "border-transparent hover:bg-accent/60",
        )}
      >
        <AssetIcon src={asset?.icon} symbol={symbol} />
        <span className="min-w-0">
          <span className="block text-[13px] leading-tight font-semibold">{symbol}</span>
          <span className="block truncate text-[11px] leading-tight text-muted-foreground">{asset?.name ?? "—"}</span>
        </span>
        <span className="text-right">
          <span key={flash?.n} className={cn("num block rounded-sm px-1 text-[12px]", flash && `flash-${flash.dir}`)}>
            {price(live?.price)}
          </span>
          <Delta value={live?.change_24h} className="block px-1 text-[10px]" />
        </span>
      </button>
      <button
        onClick={onRemove}
        aria-label={`Remove ${symbol} from watchlist`}
        className="absolute top-1 right-1 hidden rounded-sm p-0.5 text-muted-foreground group-hover:block hover:text-foreground"
      >
        <X className="size-3" />
      </button>
    </li>
  );
}

export function Watchlist({
  symbols,
  selected,
  catalog,
  onSelect,
  onRemove,
}: {
  symbols: string[];
  selected: string;
  catalog: Catalog;
  onSelect: (symbol: string) => void;
  onRemove: (symbol: string) => void;
}) {
  return (
    <Panel title="Watchlist" meta={`${symbols.length} names · live`} delay={60}>
      {symbols.length === 0 ? (
        <Empty>Star an instrument to follow it here.</Empty>
      ) : (
        <ul className="scroll-thin min-h-0 overflow-y-auto py-1">
          {symbols.map((symbol) => (
            <Row
              key={symbol}
              symbol={symbol}
              active={symbol === selected}
              catalog={catalog}
              onSelect={() => onSelect(symbol)}
              onRemove={() => onRemove(symbol)}
            />
          ))}
        </ul>
      )}
    </Panel>
  );
}

function TapeItem({ symbol, cls, onSelect }: { symbol: string; cls: ProductClass; onSelect: (symbol: string) => void }) {
  const { live } = useTicker(symbol, cls);
  return (
    <button onClick={() => onSelect(symbol)} className="flex shrink-0 items-baseline gap-2 px-5 hover:text-chart-1">
      <span className="text-[11px] font-semibold tracking-wide">{symbol}</span>
      <span className="num text-[11px]">{price(live?.price)}</span>
      <Delta value={live?.change_1h} className="text-[10px]" />
    </button>
  );
}

/** The ticker tape: watchlist prices with 1h change, scrolling; pauses on hover. */
export function Tape({ symbols, catalog, onSelect }: { symbols: string[]; catalog: Catalog; onSelect: (symbol: string) => void }) {
  if (symbols.length === 0) return null;
  return (
    <div className="tape relative overflow-hidden border-b bg-card/40 py-1.5" aria-label="Ticker tape">
      <div className="tape-track flex w-max">
        {[0, 1].map((copy) => (
          <div key={copy} className="flex" aria-hidden={copy === 1}>
            {symbols.map((symbol) => (
              <TapeItem key={symbol} symbol={symbol} cls={catalog.classOf(symbol)} onSelect={onSelect} />
            ))}
            <span className="kicker shrink-0 px-5">1h change</span>
          </div>
        ))}
      </div>
    </div>
  );
}
