import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { webcrypto } from "node:crypto";
import type { IncomingMessage } from "node:http";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { createTradingService, sameApp, TradeError } from "./trading";

// A throwaway P-256 key in the True Markets key-file format; the API is faked, so nothing leaves the test.
let keyFile = "";
beforeAll(async () => {
  const pair = await webcrypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, true, ["sign", "verify"]);
  const jwk = await webcrypto.subtle.exportKey("jwk", pair.privateKey);
  keyFile = join(mkdtempSync(join(tmpdir(), "tm-key-")), "key.json");
  writeFileSync(keyFile, JSON.stringify({ key_id: "11111111-2222-3333-4444-555555555555", private_key: jwk, algorithm: "ES256" }));
});

const USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v";
const SOL = "So11111111111111111111111111111111111111112";
const asset = (over: { id: string; symbol: string; [key: string]: unknown }) => ({ venue: "defi", type: "spot", asset_class: "crypto", tradeable: true, status: "active", decimals: 9, stable: false, chain: "solana", name: "x", ...over });
const ASSETS = [
  asset({ id: "495e07ac-fa3e-4179-85b7-b1e8cece3dc4", symbol: "SOL", address: SOL }),
  asset({ id: "9021d7aa-2af9-4157-82f9-d6eadea5701a", symbol: "USDC", address: USDC, stable: true, decimals: 6 }),
  asset({ id: "b2538174-aae3-4b55-b79f-ac177c99f816", symbol: "BTC", venue: "cefi", chain: null, address: null }),
  asset({ id: "c3538174-aae3-4b55-b79f-ac177c99f816", symbol: "NVDA", asset_class: "stock", address: "nvda" }),
];
const SOL_ID = ASSETS[0].id;

function fakeApi(overrides: Partial<Record<string, (init?: RequestInit) => unknown>> = {}) {
  const calls: { method: string; path: string; body?: unknown }[] = [];
  const routes: Record<string, (init?: RequestInit) => unknown> = {
    "POST /v1/auth/api-key/token": () => ({ access_token: "access", refresh_token: "refresh", expires_in: "2099-01-01T00:00:00Z" }),
    "GET /v1/gateway/assets": () => ({ data: ASSETS }),
    "GET /v1/gateway/assets/availability": () => ({ country: "US", allowed_product_types: ["spot"], allowed_asset_classes: ["crypto"] }),
    "POST /v1/gateway/orders": (init) => {
      const body = JSON.parse(String(init?.body));
      const buy = body.side === "buy";
      return { order_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", status: "initialized", payloads: [{ payload: "tx-1" }, { payload: "tx-2" }],
        quote: { base_asset: SOL, quote_asset: USDC, qty: body.qty, qty_out: buy ? "0.0098" : String(Number(body.qty) * 101), fee: "0.002", fee_asset: USDC, issues: [] } };
    },
    "POST /v1/gateway/orders/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/execute": () => ({ status: "pending" }),
    "GET /v1/gateway/orders/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee": () => ({ status: "complete", executed_qty: "0.0098", explorer_url: "https://solscan.io/tx/x" }),
    ...overrides,
  };
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.replace("https://api.truemarkets.co", "").split("?")[0];
    const method = init?.method ?? "GET";
    calls.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const route = routes[`${method} ${path}`];
    if (!route) return new Response(JSON.stringify({ message: "not found" }), { status: 404 });
    const result = route(init);
    return result instanceof Response ? result : new Response(JSON.stringify(result), { status: 200 });
  });
  return { fetch: fetch as unknown as typeof globalThis.fetch, calls };
}

const service = (api: ReturnType<typeof fakeApi>, over: Partial<Parameters<typeof createTradingService>[0]> = {}) =>
  createTradingService({ keyFile, enabled: true, maxOrderUsd: 10, dailyLimitUsd: 25, fetch: api.fetch, ...over });

describe("trading guardrails", () => {
  it("previews a buy without executing it", async () => {
    const api = fakeApi();
    const preview = await service(api).preview({ assetId: SOL_ID, side: "buy", amount: "2" });
    expect(preview).toMatchObject({ symbol: "SOL", side: "buy", pay: { amount: "2", symbol: "USDC" }, receive: { amount: "0.0098", symbol: "SOL" }, notionalUsd: 2 });
    expect(api.calls.find((c) => c.path === "/v1/gateway/orders")?.body).toEqual({ asset_id: SOL_ID, qty: "2", qty_unit: "quote", side: "buy", type: "market" });
    expect(api.calls.some((c) => c.path.endsWith("/execute"))).toBe(false);
  });

  it("refuses assets the account can't trade, before quoting", async () => {
    const api = fakeApi();
    const s = service(api);
    await expect(s.preview({ assetId: ASSETS[2].id, side: "buy", amount: "2" })).rejects.toThrow(/CeFi exchange/);
    await expect(s.preview({ assetId: ASSETS[3].id, side: "buy", amount: "2" })).rejects.toThrow(/isn't available in US/);
    await expect(s.preview({ assetId: ASSETS[1].id, side: "buy", amount: "2" })).rejects.toThrow(/stablecoin/);
    expect(api.calls.some((c) => c.path === "/v1/gateway/orders")).toBe(false);
  });

  it("caps order size for buys and for the proceeds of sells", async () => {
    const s = service(fakeApi());
    await expect(s.preview({ assetId: SOL_ID, side: "buy", amount: "10.01" })).rejects.toThrow(/capped at \$10/);
    await expect(s.preview({ assetId: SOL_ID, side: "sell", amount: "0.2" })).rejects.toThrow(/worth about \$20.20/);
    await expect(s.preview({ assetId: SOL_ID, side: "buy", amount: "-1" })).rejects.toThrow();
  });

  it("won't execute while trading is switched off", async () => {
    const api = fakeApi();
    const s = service(api, { enabled: false });
    const preview = await s.preview({ assetId: SOL_ID, side: "buy", amount: "2" });
    await expect(s.execute(preview.previewId)).rejects.toMatchObject({ code: "trading_disabled" });
    expect(api.calls.some((c) => c.path.endsWith("/execute"))).toBe(false);
  });

  it("signs every payload, executes once, and follows the order to a final state", async () => {
    const api = fakeApi();
    const s = service(api);
    const preview = await s.preview({ assetId: SOL_ID, side: "buy", amount: "2" });
    const result = await s.execute(preview.previewId);
    expect(result).toMatchObject({ status: "complete", executedQty: "0.0098", explorerUrl: "https://solscan.io/tx/x" });
    const execute = api.calls.find((c) => c.path.endsWith("/execute"))!.body as { signatures: string[]; auth_type: string };
    expect(execute.auth_type).toBe("api_key");
    expect(execute.signatures).toHaveLength(2);
    const stamp = JSON.parse(Buffer.from(execute.signatures[0], "base64url").toString());
    expect(stamp).toMatchObject({ scheme: "SIGNATURE_SCHEME_TK_API_P256" });
    expect(stamp.publicKey).toMatch(/^0[23][0-9a-f]{64}$/);
    await expect(s.execute(preview.previewId)).rejects.toMatchObject({ code: "already_submitted" });
  });

  it("rejects stale quotes and enforces the 24h limit", async () => {
    let now = 1_000_000;
    const api = fakeApi();
    const s = service(api, { now: () => now, dailyLimitUsd: 5 });
    const stale = await s.preview({ assetId: SOL_ID, side: "buy", amount: "2" });
    now += 101_000;
    await expect(s.execute(stale.previewId)).rejects.toMatchObject({ code: "quote_stale" });
    const first = await s.preview({ assetId: SOL_ID, side: "buy", amount: "4" });
    await s.execute(first.previewId);
    const second = await s.preview({ assetId: SOL_ID, side: "buy", amount: "2" });
    await expect(s.execute(second.previewId)).rejects.toMatchObject({ code: "over_daily_cap" });
  });

  it("surfaces True Markets errors such as quote_stale on execute", async () => {
    const api = fakeApi({ "POST /v1/gateway/orders/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/execute": () => new Response(JSON.stringify({ code: "quote_stale", message: "Quote expired" }), { status: 422 }) });
    const s = service(api);
    const preview = await s.preview({ assetId: SOL_ID, side: "buy", amount: "2" });
    await expect(s.execute(preview.previewId)).rejects.toBeInstanceOf(TradeError);
  });
});

describe("sameApp", () => {
  const req = (headers: Record<string, string>) => ({ headers: { host: "localhost:5180", ...headers } }) as unknown as IncomingMessage;
  it("requires the app header and a matching origin", () => {
    expect(sameApp(req({ "x-alphacouncil": "1", origin: "http://localhost:5180" }))).toBe(true);
    expect(sameApp(req({ "x-alphacouncil": "1" }))).toBe(true);
    expect(sameApp(req({ origin: "http://localhost:5180" }))).toBe(false);
    expect(sameApp(req({ "x-alphacouncil": "1", origin: "https://evil.example" }))).toBe(false);
  });
});
