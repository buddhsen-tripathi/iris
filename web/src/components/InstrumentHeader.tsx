import { useQuery } from "@tanstack/react-query";
import { Star } from "lucide-react";
import type { ReactNode } from "react";
import { useTopic } from "@/hooks/useMarket";
import { compact, decimalsFor, price, size } from "@/lib/format";
import { tm, topics, type Asset, type LivePrice, type ProductClass } from "@/lib/tm";
import { cn } from "@/lib/utils";
import { AssetIcon, Delta } from "./ui";

function Stat({ label, children, title }: { label: string; children: ReactNode; title?: string }) {
  return (
    <div className="min-w-0 border-l pl-3" title={title}>
      <div className="kicker">{label}</div>
      <div className="num mt-1 truncate text-[13px]">{children}</div>
    </div>
  );
}

/** Where the live price sits inside the 24h low–high band. */
function RangeBar({ low, high, last }: { low?: number; high?: number; last?: number }) {
  const ok = low !== undefined && high !== undefined && last !== undefined && high > low;
  const at = ok ? Math.min(1, Math.max(0, (last - low) / (high - low))) : 0.5;
  return (
    <div className="min-w-40 border-l pl-3">
      <div className="kicker">24h range</div>
      <div className="relative mt-2 h-1 rounded-full bg-muted">
        <span
          className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-background bg-chart-1 transition-[left] duration-500"
          style={{ left: `${at * 100}%` }}
        />
      </div>
      <div className="num mt-1.5 flex justify-between text-[10px] text-muted-foreground">
        <span>{price(low)}</span>
        <span>{price(high)}</span>
      </div>
    </div>
  );
}

export function InstrumentHeader({
  symbol,
  cls,
  asset,
  hasPerp,
  starred,
  onStar,
}: {
  symbol: string;
  cls: ProductClass;
  asset?: Asset;
  hasPerp: boolean;
  starred: boolean;
  onStar: () => void;
}) {
  const live = useTopic<LivePrice>(topics.price(symbol, cls)).value?.data;
  const range = useQuery({ queryKey: ["range", symbol, cls], queryFn: () => tm.range(symbol, cls), refetchInterval: 60_000 });
  const cap = useQuery({ queryKey: ["cap", symbol], queryFn: () => tm.marketCap(symbol), staleTime: 5 * 60_000, retry: false });
  const perp = useQuery({
    queryKey: ["perp", symbol],
    queryFn: () => tm.perpHistory(symbol),
    enabled: hasPerp,
    refetchInterval: 60_000,
    retry: false,
  });
  const last = Number(live?.price);
  const funding = perp.data?.points.at(-1);
  const rate = Number(funding?.funding_rate);
  const oi = Number(funding?.open_interest);

  return (
    <div className="rise flex flex-wrap items-end gap-x-6 gap-y-3 px-5 pt-4 pb-3" style={{ animationDelay: "40ms" }}>
      <div className="flex items-end gap-3">
        <AssetIcon src={asset?.icon} symbol={symbol} className="mb-1.5 size-9" />
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-sm font-semibold tracking-wide">{symbol}</h1>
            <span className="text-xs text-muted-foreground">{asset?.name}</span>
            {asset && (
              <span className="kicker rounded-sm border px-1 py-px">
                {cls === "perp" ? "perp" : asset.asset_class === "stock" ? "tokenized stock" : (asset.chain ?? asset.venue)}
              </span>
            )}
            <button
              onClick={onStar}
              aria-pressed={starred}
              aria-label={starred ? "Remove from watchlist" : "Add to watchlist"}
              className="text-muted-foreground hover:text-foreground"
            >
              <Star className={cn("size-3.5", starred && "fill-chart-1 text-chart-1")} />
            </button>
          </div>
          <div className="flex items-baseline gap-3">
            <span className="text-[2.5rem] leading-[1.1] font-semibold tracking-tight tabular-nums">{price(live?.price, decimalsFor(last))}</span>
            <span className="flex flex-col text-[11px] leading-snug">
              <span>
                <span className="kicker mr-1">1h</span>
                <Delta value={live?.change_1h} />
              </span>
              <span>
                <span className="kicker mr-1">24h</span>
                <Delta value={live?.change_24h} />
              </span>
            </span>
          </div>
        </div>
      </div>
      <div className="ml-auto flex flex-wrap items-end gap-x-4 gap-y-2">
        <RangeBar
          low={range.data ? Number(range.data.min_price) : undefined}
          high={range.data ? Number(range.data.max_price) : undefined}
          last={Number.isFinite(last) ? last : undefined}
        />
        <Stat label="Market cap">{compact(cap.data?.market_cap, "$")}</Stat>
        {hasPerp && (
          <>
            <Stat label="Funding 1h" title="Latest hourly perp funding rate; annualised as rate × 24 × 365">
              {Number.isFinite(rate) ? (
                <>
                  <span className={cn(rate > 0 ? "text-up" : rate < 0 ? "text-down" : "")}>{(rate * 100).toFixed(4)}%</span>
                  <span className="ml-1.5 text-[10px] text-muted-foreground">{(rate * 24 * 365 * 100).toFixed(1)}% ann.</span>
                </>
              ) : (
                "—"
              )}
            </Stat>
            <Stat label="Open interest" title="Perp open interest in base units, with notional at the live price">
              {Number.isFinite(oi) ? (
                <>
                  {size(oi)} <span className="text-[10px] text-muted-foreground">{symbol}</span>
                  {Number.isFinite(last) && <span className="ml-1.5 text-[10px] text-muted-foreground">≈ {compact(oi * last, "$")}</span>}
                </>
              ) : (
                "—"
              )}
            </Stat>
          </>
        )}
      </div>
    </div>
  );
}
