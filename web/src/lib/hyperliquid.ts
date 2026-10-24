import { insertPrints, toPrint, type HlTrade, type Print } from "./flow";

// Public Hyperliquid trade stream (https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket).
// True Markets' order book comes from the same Hyperliquid perps; its CeFi TRADE channel exists but
// its books printed nothing over the last 24h, so taker flow is read from the venue that trades.

const URL = "wss://api.hyperliquid.xyz/ws";
export const RETAIN_MS = 30 * 60_000;

type Coin = { log: Print[]; since: number; listeners: Set<() => void>; version: number };

class HyperliquidTrades {
  private ws: WebSocket | null = null;
  private coins = new Map<string, Coin>();
  private retries = 0;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private ping: ReturnType<typeof setInterval> | undefined;

  /** Follows a coin's trades (e.g. "BTC", "xyz:NVDA"). Prints are kept for 30 minutes after unsubscribe. */
  subscribe(coin: string, listener: () => void): () => void {
    let entry = this.coins.get(coin);
    const fresh = !entry || entry.listeners.size === 0;
    if (!entry) {
      entry = { log: [], since: Date.now(), listeners: new Set(), version: 0 };
      this.coins.set(coin, entry);
    }
    // A coin that went unwatched has gaps; restart its coverage clock.
    if (fresh && entry.listeners.size === 0 && Date.now() - (entry.log.at(-1)?.time ?? 0) > 5000) {
      entry.log = [];
      entry.since = Date.now();
    }
    entry.listeners.add(listener);
    if (fresh) this.send("subscribe", coin);
    this.ensureOpen();
    return () => {
      entry.listeners.delete(listener);
      if (entry.listeners.size === 0) this.send("unsubscribe", coin);
    };
  }

  snapshot(coin: string): { log: Print[]; since: number; version: number } | undefined {
    return this.coins.get(coin);
  }

  private send(method: "subscribe" | "unsubscribe", coin: string) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ method, subscription: { type: "trades", coin } }));
  }

  private ensureOpen() {
    if (this.ws || this.retryTimer) return;
    const ws = new WebSocket(URL);
    this.ws = ws;
    ws.onopen = () => {
      this.retries = 0;
      for (const [coin, entry] of this.coins) {
        if (!entry.listeners.size) continue;
        // Coverage restarts after a disconnect; earlier prints stay but the gap is not filled.
        if (Date.now() - (entry.log.at(-1)?.time ?? 0) > 5000) entry.since = Date.now();
        this.send("subscribe", coin);
      }
      // The server drops connections that are silent for 60s.
      this.ping = setInterval(() => ws.readyState === WebSocket.OPEN && ws.send('{"method":"ping"}'), 30_000);
    };
    ws.onmessage = (event) => {
      let message: { channel?: string; data?: HlTrade[] };
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      if (message.channel !== "trades" || !Array.isArray(message.data) || !message.data.length) return;
      const entry = this.coins.get(message.data[0].coin);
      if (!entry) return;
      const prints = message.data.map(toPrint).filter((p): p is Print => p !== null);
      entry.log = insertPrints(entry.log, prints, Date.now() - RETAIN_MS);
      entry.version++;
      entry.listeners.forEach((listener) => listener());
    };
    ws.onclose = () => {
      clearInterval(this.ping);
      this.ws = null;
      if (![...this.coins.values()].some((c) => c.listeners.size)) return;
      const delay = Math.min(15000, 1000 * 2 ** this.retries++);
      this.retryTimer = setTimeout(() => {
        this.retryTimer = undefined;
        this.ensureOpen();
      }, delay);
    };
  }
}

export const hyperliquidTrades = new HyperliquidTrades();
