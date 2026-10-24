import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { tm, type Asset, type ProductClass } from "@/lib/tm";

export type Catalog = {
  /** One entry per symbol (upper-case): the spot listing if there is one, else the perp listing. */
  bySymbol: Map<string, Asset>;
  /** Every searchable instrument, sorted by symbol. */
  all: Asset[];
  /** Symbols with a Hyperliquid perp listing, which have an order book and funding data. */
  perps: Set<string>;
  /** Spot-listed symbols chart as candles; perp-only symbols (e.g. XRP, DOGE) chart their perp price. */
  classOf: (symbol: string) => ProductClass;
};

function index(assets: Asset[] | undefined, into: Map<string, Asset>) {
  for (const asset of assets ?? []) {
    if (!asset.tradeable || asset.stable) continue;
    const k = asset.symbol.toUpperCase();
    const existing = into.get(k);
    if (!existing || (!existing.icon && asset.icon)) into.set(k, asset);
  }
  return into;
}

export function useCatalog(): Catalog {
  const spot = useQuery({ queryKey: ["assets", "spot"], queryFn: () => tm.assets("spot"), staleTime: 10 * 60_000 });
  const perp = useQuery({ queryKey: ["assets", "perp"], queryFn: () => tm.assets("perp"), staleTime: 10 * 60_000 });
  return useMemo(() => {
    const spotBySymbol = index(spot.data?.data, new Map());
    const perpBySymbol = index(perp.data?.data, new Map());
    const bySymbol = new Map(spotBySymbol);
    for (const [k, asset] of perpBySymbol) if (!bySymbol.has(k)) bySymbol.set(k, asset);
    return {
      bySymbol,
      all: [...bySymbol.values()].sort((a, b) => a.symbol.localeCompare(b.symbol)),
      perps: new Set(perpBySymbol.keys()),
      classOf: (symbol: string) => (spotBySymbol.has(symbol) || !perpBySymbol.has(symbol) ? "spot" : "perp"),
    };
  }, [spot.data, perp.data]);
}
