import type { Timeframe } from "./timeframes";

export { TIMEFRAMES, type Timeframe } from "./timeframes";

// Read-only client for True Markets public market data. No account, token, or order endpoints.
// Spec: https://docs.truemarkets.co/openapi/marketdata.yaml

const TM_REST = import.meta.env.VITE_TM_REST ?? "/tm";
export const TM_WS = import.meta.env.VITE_TM_WS ?? "wss://api.truemarkets.co/v1/defi/market";

export class TmError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly type?: string,
    readonly requestId?: string,
  ) {
    super(message);
  }
}

type Params = Record<string, string | number | undefined>;

async function get<T>(path: string, params: Params = {}, signal?: AbortSignal): Promise<T> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined) query.set(key, String(value));
  const response = await fetch(`${TM_REST}${path}?${query}`, { signal, headers: { Accept: "application/json" } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new TmError(response.status, body.message ?? response.statusText, body.type, body.request_id);
  }
  return response.json();
}


export type Candle = { t: string; open: string; high: string; low: string; close: string };
type CandleResponse = { asset_id: string; symbol: string; window: string; resolution: string; candles: Candle[] };
export type Point = { t: string; value: string };
type IndicatorResponse = { indicator: string; lines: Record<string, Point[]> };
type PerpPoint = { t: string; funding_rate: string; open_interest: string };
type PriceRange = { min_price: string; max_price: string; min_timestamp: string; max_timestamp: string };
type TrendingAsset = {
  asset_id: string;
  symbol: string;
  chain: string;
  market_cap: string;
  trending_ratio: string;
  recent_volume: string;
  historical_volume: string;
};
type SurgingAsset = {
  asset_id: string;
  symbol: string;
  chain: string;
  price_change_pct_1h: string;
  price_change_pct_4h: string;
  price_change_pct_24h: string;
  current_price: string;
};
export type Asset = {
  id: string;
  symbol: string;
  name: string;
  chain: string | null;
  venue: "defi" | "cefi";
  type: "spot" | "perp";
  asset_class: "crypto" | "stock";
  icon?: string;
  stable: boolean;
  tradeable: boolean;
};

export type IndicatorKind = "sma" | "ema" | "bollinger" | "rsi" | "macd";

/** How a symbol is priced: spot listings have trade-built OHLC candles; perp-only listings have price samples. */
export type ProductClass = "spot" | "perp";

export const tm = {
  candles: (symbol: string, tf: Timeframe, signal?: AbortSignal) =>
    get<CandleResponse>("/v1/defi/market/prices/candles", { symbol, window: tf.window, resolution: tf.resolution }, signal),
  priceHistory: (symbol: string, tf: Timeframe, assetClass: ProductClass, signal?: AbortSignal) =>
    get<{ points: { t: string; price: string }[] }>(
      "/v1/defi/market/prices/history",
      { symbol, asset_class: assetClass, window: tf.window, resolution: tf.resolution },
      signal,
    ),
  indicator: (symbol: string, assetClass: ProductClass, tf: Timeframe, indicator: IndicatorKind, period?: number, signal?: AbortSignal) =>
    get<IndicatorResponse>(
      "/v1/defi/market/prices/indicators",
      { symbol, asset_class: assetClass, indicator, period, window: tf.window, resolution: tf.resolution },
      signal,
    ),
  range: (symbol: string, assetClass: ProductClass, window = "1d") =>
    get<PriceRange>("/v1/defi/market/prices/range", { symbol, asset_class: assetClass, window }),
  marketCap: (symbol: string) => get<{ symbol: string; market_cap: string }>("/v1/defi/market/market-data/market-cap", { symbol }),
  perpHistory: (symbol: string) =>
    get<{ points: PerpPoint[] }>("/v1/defi/market/market-data/perp/history", { symbol, window: "1d", resolution: "1h" }),
  trending: (limit = 12) => get<{ assets: TrendingAsset[] }>("/v1/defi/market/market-data/trending", { limit }),
  surging: (limit = 12) => get<{ assets: SurgingAsset[] }>("/v1/defi/market/market-data/surging", { limit }),
  marketCaps: (limit = 12) =>
    get<{ assets: { symbol: string; market_cap: string }[] }>("/v1/defi/market/market-data/market-caps", { limit }),
  assets: (productType: string, assetClass = "crypto,stock") =>
    get<{ data: Asset[] }>("/v1/gateway/assets", { product_type: productType, asset_class: assetClass }),
};

// WebSocket payloads (asyncapi/marketdata.yaml).
export type LivePrice = {
  symbol: string;
  asset_class: "spot" | "perp";
  price: string;
  change_1h?: string;
  change_24h?: string;
  timestamp: string;
};
export type SourceBBO = { source: string; bid: string; ask: string; mid_price: string; weight_pct: string; timestamp: string };
export type ReferencePrice = {
  symbol: string;
  instrument?: string;
  mid_price: string;
  bid: string;
  ask: string;
  sources: SourceBBO[];
  timestamp: string;
};
export type BookLevel = { px: string; sz: string; n: number };
export type OrderBook = {
  venue: string;
  pair: string;
  coin: string;
  bids: BookLevel[];
  asks: BookLevel[];
  event_timestamp: string;
  occurred_at: string;
};

export const topics = {
  price: (symbol: string, cls: ProductClass = "spot") => (cls === "perp" ? `price.${symbol}-PERP` : `price.${symbol}`),
  reference: (symbol: string) => `reference.${symbol}`,
  perpBook: (symbol: string) => `orderbook.hyperliquid-perp.${symbol}-USD`,
};
