import { TM_WS } from "./tm";

type SocketStatus = "idle" | "connecting" | "open" | "reconnecting";

type Message = { type: string; topics?: string[]; data?: unknown; status?: string; rejected?: { topic: string; reason: string }[] };
type Listener = () => void;

// The server canonicalises symbols upper-case ("price.kBONK" comes back as "price.KBONK"), so route case-insensitively.
const key = (topic: string) => topic.toLowerCase();

/**
 * One shared connection to the public market-data WebSocket. Topics are reference-counted across
 * components, subscribed in batches, replayed after reconnects, and the latest payload per topic is
 * cached so late subscribers render immediately.
 */
class MarketSocket {
  private ws: WebSocket | null = null;
  private listeners = new Map<string, Set<Listener>>();
  private names = new Map<string, string>();
  private latest = new Map<string, { data: unknown; receivedAt: number }>();
  private rejected = new Map<string, string>();
  private pending = new Set<string>();
  private flushQueued = false;
  private retries = 0;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private statusListeners = new Set<Listener>();
  status: SocketStatus = "idle";

  constructor(private readonly url: string) {}

  subscribe(topic: string, listener: Listener): () => void {
    const k = key(topic);
    let set = this.listeners.get(k);
    if (!set) {
      set = new Set();
      this.listeners.set(k, set);
      this.names.set(k, topic);
      this.pending.add(topic);
      this.queueFlush();
    }
    set.add(listener);
    this.ensureOpen();
    return () => {
      set.delete(listener);
      if (set.size > 0) return;
      this.listeners.delete(k);
      this.names.delete(k);
      this.latest.delete(k);
      this.rejected.delete(k);
      this.pending.delete(topic);
      this.send({ type: "unsubscribe", topics: [topic] });
    };
  }

  snapshot<T>(topic: string): { data: T; receivedAt: number } | undefined {
    return this.latest.get(key(topic)) as { data: T; receivedAt: number } | undefined;
  }

  rejection(topic: string): string | undefined {
    return this.rejected.get(key(topic));
  }

  onStatus(listener: Listener): () => void {
    this.statusListeners.add(listener);
    return () => this.statusListeners.delete(listener);
  }

  private setStatus(status: SocketStatus) {
    this.status = status;
    this.statusListeners.forEach((listener) => listener());
  }

  private ensureOpen() {
    if (this.ws || this.retryTimer) return;
    this.setStatus(this.retries ? "reconnecting" : "connecting");
    const ws = new WebSocket(this.url);
    this.ws = ws;
    ws.onopen = () => {
      this.retries = 0;
      this.setStatus("open");
      this.pending = new Set(this.names.values());
      this.flush();
    };
    ws.onmessage = (event) => this.receive(event.data);
    ws.onclose = () => {
      this.ws = null;
      if (this.listeners.size === 0) return this.setStatus("idle");
      // Exponential backoff, 1s to 15s.
      const delay = Math.min(15000, 1000 * 2 ** this.retries++);
      this.setStatus("reconnecting");
      this.retryTimer = setTimeout(() => {
        this.retryTimer = undefined;
        this.ensureOpen();
      }, delay);
    };
  }

  private receive(raw: string) {
    let message: Message;
    try {
      message = JSON.parse(raw);
    } catch {
      return;
    }
    if (message.type === "subscribe") {
      for (const { topic, reason } of message.rejected ?? []) {
        this.rejected.set(key(topic), reason);
        this.notify(key(topic));
      }
      return;
    }
    const topic = message.topics?.[0];
    if (!topic || message.data === undefined) return;
    const k = key(topic);
    if (!this.listeners.has(k)) return;
    this.latest.set(k, { data: message.data, receivedAt: Date.now() });
    this.notify(k);
  }

  private notify(k: string) {
    this.listeners.get(k)?.forEach((listener) => listener());
  }

  private queueFlush() {
    if (this.flushQueued) return;
    this.flushQueued = true;
    queueMicrotask(() => {
      this.flushQueued = false;
      this.flush();
    });
  }

  private flush() {
    if (this.pending.size === 0 || this.ws?.readyState !== WebSocket.OPEN) return;
    this.send({ type: "subscribe", topics: [...this.pending] });
    this.pending.clear();
  }

  private send(message: { type: string; topics: string[] }) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(message));
  }
}

export const marketSocket = new MarketSocket(TM_WS);
