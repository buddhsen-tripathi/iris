// Client for the dev server's /trade endpoints (server/trading.ts). The custom header marks requests as
// coming from this app; the server rejects anything without it.

const HEADERS = { "X-AlphaCouncil": "1", "Content-Type": "application/json" };

class TradeRequestError extends Error {
  constructor(
    message: string,
    readonly code?: string,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { ...init, headers: { ...HEADERS, ...init.headers } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new TradeRequestError(body.message ?? `Request failed (${response.status})`, body.code);
  return body as T;
}

type TradeStatus = {
  keyConfigured: boolean;
  enabled: boolean;
  maxOrderUsd?: number;
  dailyLimitUsd?: number;
  usedTodayUsd?: number | null;
  country?: string | null;
};

type Holding = {
  asset_id: string;
  symbol: string;
  name: string;
  chain: string | null;
  icon?: string;
  stable: boolean;
  total: string;
  available: string;
  price?: string;
  value?: string;
  change_24h_pct?: string;
};

type Account = {
  portfolio: {
    total_usd?: string;
    cash_usd?: string;
    change_24h_usd?: string;
    change_24h_pct?: string;
    unrealized_pnl_usd?: string;
    balances?: Holding[];
    positions?: unknown[];
  };
  orders: Record<string, unknown>[];
  transactions: Record<string, unknown>[];
  fetchedAt: string;
};

export type TradePreview = {
  previewId: string;
  symbol: string;
  side: "buy" | "sell";
  pay: { amount: string; symbol: string };
  receive: { amount: string; symbol: string };
  fee: { amount: string; symbol: string };
  notionalUsd: number;
  issues: string[];
  expiresAt: string;
};

export type TradeResult = {
  orderId: string;
  status: string;
  executedQty: string | null;
  executedVwap: string | null;
  fee: string | null;
  explorerUrl: string | null;
  failureReason: string | null;
};

export const trade = {
  status: () => call<TradeStatus>("/trade/status"),
  account: () => call<Account>("/trade/account"),
  tradable: (assetId: string) => call<{ reason: string | null }>(`/trade/tradable?assetId=${encodeURIComponent(assetId)}`),
  preview: (body: { assetId: string; side: "buy" | "sell"; amount: string }) => call<TradePreview>("/trade/preview", { method: "POST", body: JSON.stringify(body) }),
  execute: (previewId: string) => call<TradeResult>("/trade/execute", { method: "POST", body: JSON.stringify({ previewId, confirm: true }) }),
};
