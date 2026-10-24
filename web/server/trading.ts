import { readFileSync } from "node:fs";
import { webcrypto } from "node:crypto";
import type { IncomingMessage, ServerResponse } from "node:http";
import { neon, type NeonQueryFunction } from "@neondatabase/serverless";
import { ApiKeyStamper } from "@turnkey/api-key-stamper";
import { z } from "zod";

// Live trading through the True Markets Trading API (docs.truemarkets.co/trading-api). The API key file
// stays on this dev server; the browser only sees previews and results. Every order moves real funds, so
// every rule below is enforced here, not in the UI:
//   - trading is off unless TM_TRADING_ENABLED=true
//   - spot crypto on DeFi venues only, and only what the account's country allows; market orders only
//   - a per-order cap (TM_MAX_ORDER_USD, default 10) and a rolling 24h cap (TM_DAILY_LIMIT_USD, default 25)
//   - execution needs a fresh preview (quotes live ~2 minutes) and runs at most once per preview
//   - requests must come from this app (custom header + matching Origin), so other sites can't trigger trades

const BASE = "https://api.truemarkets.co";
const PREVIEW_TTL_MS = 100_000;
const FINAL = new Set(["complete", "failed", "canceled"]);

export class TradeError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly code?: string,
  ) {
    super(message);
  }
}

// ---------- Key, tokens, signing ----------

type KeyFile = { key_id: string; private_key: { kty: "EC"; crv: "P-256"; d: string; x: string; y: string } };

function loadKey(path: string) {
  const file = JSON.parse(readFileSync(path, "utf8")) as KeyFile;
  const jwk = file.private_key;
  if (!file.key_id || jwk?.kty !== "EC" || jwk?.crv !== "P-256" || !jwk.d) throw new Error("TM_KEY_FILE is not a True Markets P-256 key file.");
  const y = Buffer.from(jwk.y, "base64url");
  // Wallet transactions are stamped with the same key (compressed public key + private scalar as hex).
  const stamper = new ApiKeyStamper({
    apiPublicKey: Buffer.concat([Buffer.from([y[31] % 2 === 0 ? 2 : 3]), Buffer.from(jwk.x, "base64url")]).toString("hex"),
    apiPrivateKey: Buffer.from(jwk.d, "base64url").toString("hex"),
  });
  return { keyId: file.key_id, jwk, stamper };
}

type Fetch = typeof fetch;

function tokenManager(key: ReturnType<typeof loadKey>, doFetch: Fetch, now: () => number) {
  let access: { token: string; expires: number } | null = null;
  let refresh: string | null = null;
  async function mint() {
    const timestamp = Math.floor(now() / 1000);
    const signingKey = await webcrypto.subtle.importKey("jwk", { ...key.jwk, key_ops: ["sign"] }, { name: "ECDSA", namedCurve: "P-256" }, false, ["sign"]);
    const signature = await webcrypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, signingKey, new TextEncoder().encode(`${key.keyId}.${timestamp}`));
    return post("/v1/auth/api-key/token", { key_id: key.keyId, timestamp, signature: Buffer.from(signature).toString("base64url") });
  }
  async function post(path: string, body: unknown) {
    const response = await doFetch(`${BASE}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new TradeError(502, `True Markets sign-in failed (${response.status}).`, data.code);
    return data as { access_token: string; refresh_token?: string; expires_in: string };
  }
  return async function token(): Promise<string> {
    if (access && access.expires - now() > 60_000) return access.token;
    let minted;
    try {
      minted = refresh ? await post("/v1/auth/token/refresh", { refresh_token: refresh }) : await mint();
    } catch {
      minted = await mint();
    }
    refresh = minted.refresh_token ?? refresh;
    access = { token: minted.access_token, expires: Date.parse(minted.expires_in) || now() + 50 * 60_000 };
    return access.token;
  };
}

// ---------- Service ----------

type Asset = { id: string; symbol: string; name: string; chain: string | null; address: string | null; venue: string; type: string; asset_class: string; tradeable: boolean; status: string; decimals: number; stable: boolean };
type Preview = {
  orderId: string;
  payloads: { payload: string }[];
  asset: Asset;
  side: "buy" | "sell";
  qty: string;
  notionalUsd: number;
  createdAt: number;
  executed: boolean;
};

type TradingConfig = {
  keyFile?: string;
  enabled: boolean;
  maxOrderUsd: number;
  dailyLimitUsd: number;
  databaseUrl?: string;
  fetch?: Fetch;
  now?: () => number;
  sql?: NeonQueryFunction<false, false>;
};

const OrderRequest = z.object({
  assetId: z.string().uuid(),
  side: z.enum(["buy", "sell"]),
  // Buys are sized in dollars spent; sells in units of the asset sold (the API's quote/base units).
  amount: z.string().regex(/^\d+(\.\d+)?$/).refine((v) => Number(v) > 0, "Amount must be positive"),
});

export function createTradingService(config: TradingConfig) {
  const doFetch = config.fetch ?? fetch;
  const now = config.now ?? Date.now;
  const key = config.keyFile ? loadKey(config.keyFile) : null;
  const token = key ? tokenManager(key, doFetch, now) : null;
  const sql = config.sql ?? (config.databaseUrl ? neon(config.databaseUrl) : undefined);
  const previews = new Map<string, Preview>();
  const executedLocally: { at: number; usd: number }[] = [];
  let catalog: { at: number; assets: Asset[] } | null = null;
  let availability: { at: number; types: string[]; classes: string[]; country: string } | null = null;

  async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
    if (!token) throw new TradeError(503, "No True Markets key is configured.");
    const response = await doFetch(`${BASE}${path}`, {
      ...init,
      headers: { Authorization: `Bearer ${await token()}`, "Content-Type": "application/json", Accept: "application/json", ...init.headers },
      signal: AbortSignal.timeout(20_000),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new TradeError(response.status === 401 ? 502 : response.status, body.message ?? `True Markets answered ${response.status}.`, body.code);
    return body as T;
  }

  async function assets(): Promise<Asset[]> {
    if (catalog && now() - catalog.at < 10 * 60_000) return catalog.assets;
    const response = await doFetch(`${BASE}/v1/gateway/assets`);
    const data = (await response.json()) as { data: Asset[] };
    catalog = { at: now(), assets: data.data };
    return data.data;
  }

  async function allowed() {
    if (availability && now() - availability.at < 10 * 60_000) return availability;
    const a = await api<{ country: string; allowed_product_types: string[]; allowed_asset_classes: string[] }>("/v1/gateway/assets/availability");
    availability = { at: now(), country: a.country, types: a.allowed_product_types, classes: a.allowed_asset_classes };
    return availability;
  }

  /** Why an asset can't be traded here, or null when it can. */
  async function blockedReason(asset: Asset | undefined): Promise<string | null> {
    if (!asset) return "Unknown asset.";
    const rules = await allowed();
    if (!asset.tradeable || asset.status !== "active") return `${asset.symbol} isn't tradeable right now.`;
    if (asset.venue !== "defi") return `${asset.symbol} trades on the CeFi exchange, which isn't enabled for this account.`;
    if (asset.stable) return `${asset.symbol} is a stablecoin.`;
    if (!rules.types.includes(asset.type) || !rules.classes.includes(asset.asset_class)) return `${asset.symbol} isn't available in ${rules.country}.`;
    return null;
  }

  async function usedLast24h(): Promise<number> {
    const since = now() - 24 * 3600_000;
    if (sql) {
      const [row] = await sql`select coalesce(sum(notional_usd), 0)::float as used from trade_orders where executed_at > ${new Date(since).toISOString()} and coalesce(final_status, 'pending') <> 'failed'`;
      return Number(row.used);
    }
    return executedLocally.filter((e) => e.at > since).reduce((sum, e) => sum + e.usd, 0);
  }

  async function record(preview: Preview, fields: { status: string; finalStatus?: string; error?: string; executedAt?: number; quote?: unknown }) {
    if (!sql) return;
    await sql`
      insert into trade_orders (order_id, asset_id, symbol, chain, side, qty, notional_usd, quote, status, final_status, error, executed_at)
      values (${preview.orderId}, ${preview.asset.id}, ${preview.asset.symbol}, ${preview.asset.chain}, ${preview.side}, ${preview.qty}, ${preview.notionalUsd},
              ${JSON.stringify(fields.quote ?? null)}::jsonb, ${fields.status}, ${fields.finalStatus ?? null}, ${fields.error ?? null},
              ${fields.executedAt ? new Date(fields.executedAt).toISOString() : null})
      on conflict (order_id) do update set status = excluded.status, final_status = excluded.final_status, error = excluded.error,
        executed_at = coalesce(excluded.executed_at, trade_orders.executed_at), updated_at = now()`;
  }

  return {
    configured: !!key,

    async status() {
      const rules = key ? await allowed().catch(() => null) : null;
      return {
        keyConfigured: !!key,
        enabled: config.enabled && !!key,
        maxOrderUsd: config.maxOrderUsd,
        dailyLimitUsd: config.dailyLimitUsd,
        usedTodayUsd: key ? await usedLast24h().catch(() => null) : null,
        country: rules?.country ?? null,
        logged: !!sql,
      };
    },

    /** Portfolio, balances and recent activity: read-only. */
    async account() {
      const [portfolio, orders, transactions] = await Promise.all([
        api<Record<string, unknown>>("/v1/gateway/portfolio"),
        api<{ data: Record<string, unknown>[] }>("/v1/gateway/orders?limit=10"),
        api<{ data: Record<string, unknown>[] }>("/v1/gateway/transactions?limit=10"),
      ]);
      return { portfolio, orders: orders.data, transactions: transactions.data, fetchedAt: new Date(now()).toISOString() };
    },

    async tradable(assetId: string) {
      const asset = (await assets()).find((a) => a.id === assetId);
      return { reason: await blockedReason(asset) };
    },

    /** Creates the order without executing it: a binding quote that expires in ~2 minutes. Nothing moves. */
    async preview(input: unknown) {
      const request = OrderRequest.parse(input);
      const list = await assets();
      const asset = list.find((a) => a.id === request.assetId);
      const blocked = await blockedReason(asset);
      if (blocked) throw new TradeError(422, blocked, "not_tradable");
      if (request.side === "buy" && Number(request.amount) > config.maxOrderUsd)
        throw new TradeError(422, `Orders are capped at $${config.maxOrderUsd}.`, "over_order_cap");

      const created = await api<{ order_id: string; status: string; payloads?: { payload: string }[]; quote?: { qty: string; qty_out: string; fee: string; fee_asset: string; quote_asset: string; base_asset: string; issues?: string[] } }>(
        "/v1/gateway/orders",
        { method: "POST", body: JSON.stringify({ asset_id: asset!.id, qty: request.amount, qty_unit: request.side === "buy" ? "quote" : "base", side: request.side, type: "market" }) },
      );
      const quote = created.quote;
      if (!created.order_id || !quote) throw new TradeError(422, quote?.issues?.join("; ") || "True Markets couldn't quote this order.", "no_quote");

      const byAddress = (address: string) => list.find((a) => a.address === address && a.chain === asset!.chain);
      const payAsset = byAddress(request.side === "buy" ? quote.quote_asset : quote.base_asset);
      const getAsset = byAddress(request.side === "buy" ? quote.base_asset : quote.quote_asset);
      // Dollar size: what's spent on a buy, what's received on a sell (both in the stablecoin).
      const notionalUsd = request.side === "buy" ? Number(quote.qty) : Number(quote.qty_out);
      if (!Number.isFinite(notionalUsd) || notionalUsd > config.maxOrderUsd)
        throw new TradeError(422, `This sell is worth about $${notionalUsd.toFixed(2)}; orders are capped at $${config.maxOrderUsd}.`, "over_order_cap");

      const preview: Preview = { orderId: created.order_id, payloads: created.payloads ?? [], asset: asset!, side: request.side, qty: request.amount, notionalUsd, createdAt: now(), executed: false };
      previews.set(preview.orderId, preview);
      for (const [id, p] of previews) if (now() - p.createdAt > 10 * 60_000) previews.delete(id);
      await record(preview, { status: "previewed", quote }).catch(() => {});
      return {
        previewId: preview.orderId,
        symbol: asset!.symbol,
        side: request.side,
        pay: { amount: quote.qty, symbol: payAsset?.symbol ?? "USDC" },
        receive: { amount: quote.qty_out, symbol: getAsset?.symbol ?? asset!.symbol },
        fee: { amount: quote.fee, symbol: list.find((a) => a.address === quote.fee_asset && a.chain === asset!.chain)?.symbol ?? "USDC" },
        notionalUsd,
        issues: quote.issues ?? [],
        expiresAt: new Date(preview.createdAt + PREVIEW_TTL_MS).toISOString(),
      };
    },

    /** Signs and executes a previewed order, then follows it to a final state. Moves real funds. */
    async execute(previewId: string) {
      if (!config.enabled) throw new TradeError(403, "Trading is switched off. Set TM_TRADING_ENABLED=true in web/.env.local to allow orders.", "trading_disabled");
      const preview = previews.get(previewId);
      if (!preview) throw new TradeError(404, "That preview has expired. Preview the order again.", "preview_missing");
      if (preview.executed) throw new TradeError(409, "This order was already submitted.", "already_submitted");
      if (now() - preview.createdAt > PREVIEW_TTL_MS) throw new TradeError(422, "The quote expired. Preview the order again.", "quote_stale");
      const used = await usedLast24h();
      if (used + preview.notionalUsd > config.dailyLimitUsd)
        throw new TradeError(422, `This would exceed the 24h limit of $${config.dailyLimitUsd} ($${used.toFixed(2)} used).`, "over_daily_cap");

      preview.executed = true;
      const signatures = await Promise.all(preview.payloads.map(async (p) => (await key!.stamper.stamp(p.payload)).stampHeaderValue));
      let result: { status: string };
      try {
        result = await api<{ status: string }>(`/v1/gateway/orders/${preview.orderId}/execute`, { method: "POST", body: JSON.stringify({ signatures, auth_type: "api_key" }) });
      } catch (error) {
        const message = error instanceof Error ? error.message : "Execute failed.";
        await record(preview, { status: "failed", finalStatus: "failed", error: message }).catch(() => {});
        throw error;
      }
      executedLocally.push({ at: now(), usd: preview.notionalUsd });
      await record(preview, { status: result.status, executedAt: now() }).catch(() => {});

      // Follow to a final state for a short while; anything still settling is reported as pending.
      let order: Record<string, unknown> = { status: result.status };
      const deadline = now() + 25_000;
      while (!FINAL.has(String(order.status)) && now() < deadline) {
        await new Promise((r) => setTimeout(r, 1500));
        order = await api<Record<string, unknown>>(`/v1/gateway/orders/${preview.orderId}`).catch(() => order);
      }
      await record(preview, { status: String(order.status), finalStatus: FINAL.has(String(order.status)) ? String(order.status) : undefined, error: (order.failure_reason as string) ?? undefined }).catch(() => {});
      return {
        orderId: preview.orderId,
        status: String(order.status),
        executedQty: order.executed_qty ?? null,
        executedVwap: order.executed_vwap ?? null,
        fee: order.fee ?? null,
        explorerUrl: order.explorer_url ?? null,
        failureReason: order.failure_reason ?? null,
      };
    },
  };
}

// ---------- HTTP ----------

async function readJson(req: IncomingMessage, limit = 4_000): Promise<unknown> {
  let size = 0;
  const chunks: Buffer[] = [];
  for await (const chunk of req) {
    size += chunk.length;
    if (size > limit) throw new TradeError(413, "Request too large");
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
}

/** Only this app may call /trade: a custom header forces a CORS preflight that other origins fail, and Origin must match. */
export function sameApp(req: IncomingMessage): boolean {
  if (req.headers["x-alphacouncil"] !== "1") return false;
  const origin = req.headers.origin;
  if (!origin) return true;
  try {
    return new URL(origin).host === req.headers.host;
  } catch {
    return false;
  }
}

export function tradingMiddleware(service: ReturnType<typeof createTradingService> | null) {
  return async (req: IncomingMessage, res: ServerResponse, next: () => void) => {
    if (!req.url?.startsWith("/trade/")) return next();
    const json = (status: number, body: unknown) => {
      res.statusCode = status;
      res.setHeader("Content-Type", "application/json");
      res.setHeader("Cache-Control", "no-store");
      res.end(JSON.stringify(body));
    };
    if (!sameApp(req)) return json(403, { message: "Trading requests must come from this app." });
    const path = new URL(req.url, "http://local").pathname;
    try {
      if (!service) return json(200, { keyConfigured: false, enabled: false });
      if (path === "/trade/status" && req.method === "GET") return json(200, await service.status());
      if (!service.configured) return json(503, { message: "No True Markets key is configured." });
      if (path === "/trade/account" && req.method === "GET") return json(200, await service.account());
      if (path === "/trade/tradable" && req.method === "GET") return json(200, await service.tradable(new URL(req.url, "http://local").searchParams.get("assetId") ?? ""));
      if (path === "/trade/preview" && req.method === "POST") return json(200, await service.preview(await readJson(req)));
      if (path === "/trade/execute" && req.method === "POST") {
        const body = z.object({ previewId: z.string().uuid(), confirm: z.literal(true) }).parse(await readJson(req));
        return json(200, await service.execute(body.previewId));
      }
      return json(404, { message: "Unknown trading endpoint." });
    } catch (error) {
      if (error instanceof z.ZodError) return json(400, { message: error.issues[0]?.message ?? "Invalid request." });
      if (error instanceof TradeError) return json(error.status, { message: error.message, code: error.code });
      return json(502, { message: "True Markets couldn't be reached." });
    }
  };
}
