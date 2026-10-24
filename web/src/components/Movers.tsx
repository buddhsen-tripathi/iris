import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import type { Catalog } from "@/hooks/useCatalog";
import { compact, price } from "@/lib/format";
import { tm } from "@/lib/tm";
import { AssetIcon, Delta, Empty, Panel, Segmented } from "./ui";

type Tab = "surging" | "trending" | "caps";

const TABS = [
  { id: "surging", label: "Surging", title: "Largest 1h price moves" },
  { id: "trending", label: "Trending", title: "Recent volume vs. its baseline" },
  { id: "caps", label: "Mkt cap", title: "Largest by market cap" },
] as const;

type Item = { symbol: string; chain?: string; primary: string; secondary: ReactNode };

export function Movers({ catalog, onSelect }: { catalog: Catalog; onSelect: (symbol: string) => void }) {
  const [tab, setTab] = useState<Tab>("surging");
  const query = useQuery({
    queryKey: ["movers", tab],
    queryFn: async (): Promise<Item[]> => {
      if (tab === "surging")
        return (await tm.surging()).assets.map((a) => ({
          symbol: a.symbol,
          chain: a.chain,
          primary: price(a.current_price),
          secondary: <Delta value={a.price_change_pct_1h} />,
        }));
      if (tab === "trending")
        return (await tm.trending()).assets.map((a) => ({
          symbol: a.symbol,
          chain: a.chain,
          primary: `${Number(a.trending_ratio).toFixed(1)}×`,
          secondary: <span className="num text-muted-foreground">vol {compact(a.recent_volume, "$")}</span>,
        }));
      return (await tm.marketCaps()).assets.map((a) => ({
        symbol: a.symbol,
        primary: compact(a.market_cap, "$"),
        secondary: null,
      }));
    },
    refetchInterval: 30_000,
  });

  return (
    <Panel title="Movers" delay={120}>
      <div className="px-4 pt-2 [&>div]:w-full [&_button]:flex-1">
        <Segmented label="Movers" options={TABS} value={tab} onChange={setTab} />
      </div>
      {query.isError ? (
        <Empty>{query.error.message}</Empty>
      ) : (
        <ol className="scroll-thin min-h-0 flex-1 overflow-y-auto py-1">
          {(query.data ?? []).map((item, index) => (
            <li key={`${item.symbol}:${item.chain}:${index}`}>
              <button
                onClick={() => onSelect(item.symbol.toUpperCase())}
                className="grid w-full grid-cols-[1.25rem_auto_1fr_auto] items-center gap-x-2 px-4 py-1.5 text-left hover:bg-accent/60"
              >
                <span className="num text-[10px] text-muted-foreground">{index + 1}</span>
                <AssetIcon src={catalog.bySymbol.get(item.symbol.toUpperCase())?.icon} symbol={item.symbol} className="size-4" />
                <span className="min-w-0 truncate text-[12px] font-semibold">
                  {item.symbol}
                  {item.chain && <span className="ml-1.5 text-[10px] font-normal text-muted-foreground">{item.chain}</span>}
                </span>
                <span className="text-right text-[11px] leading-tight">
                  <span className="num block">{item.primary}</span>
                  <span className="block text-[10px]">{item.secondary}</span>
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}
