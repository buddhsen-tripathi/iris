import type { IncomingMessage, ServerResponse } from "node:http";
import { XMLParser } from "fast-xml-parser";

// Live headlines from keyless RSS feeds, fetched server-side (neither feed allows browser CORS):
//   Yahoo Finance: per-ticker headlines (feeds.finance.yahoo.com/rss/2.0/headline?s=…)
//   Google News:   search and section feeds (news.google.com/rss/…)
// Both feeds are for personal, non-commercial use under their providers' terms.

export type Provider = "Yahoo Finance" | "Google News";
export type Article = { title: string; summary: string; url: string; source: string; publishedAt: string; provider: Provider };
export type AssetClass = "crypto" | "stock";

const HOUR = 3600_000;
const parser = new XMLParser({ ignoreAttributes: false, attributeNamePrefix: "", textNodeName: "text", htmlEntities: true, isArray: (name) => name === "item" });

const text = (value: unknown): string =>
  typeof value === "string" ? value : typeof value === "number" ? String(value) : ((value as { text?: unknown } | undefined)?.text as string) ?? "";
const tidy = (value: string) => value.replace(/<[^>]*>/g, "").replace(/\s+/g, " ").trim();
const isHttp = (url: string) => /^https?:\/\//i.test(url);

function publisher(url: string): string {
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
    return host.endsWith("yahoo.com") ? "Yahoo Finance" : host;
  } catch {
    return "Unknown";
  }
}

export function parseRss(xml: string, provider: Provider): Article[] {
  const items: unknown[] = parser.parse(xml)?.rss?.channel?.item ?? [];
  return items.flatMap((raw) => {
    const item = raw as Record<string, unknown>;
    let title = tidy(text(item.title));
    const url = text(item.link).trim();
    const published = Date.parse(text(item.pubDate));
    if (!title || !isHttp(url) || !Number.isFinite(published)) return [];
    const source = tidy(text(item.source)) || publisher(url);
    // Google News appends " - Publisher" to every title.
    if (title.endsWith(` - ${source}`)) title = title.slice(0, -(source.length + 3));
    const summary = tidy(text(item.description)).slice(0, 280);
    return [{ title, summary, url, source, publishedAt: new Date(published).toISOString(), provider }];
  });
}

/** Newest-first union of feeds within `maxAgeMs`, without repeated URLs or headlines. */
export function mergeArticles(lists: Article[][], nowMs: number, maxAgeMs: number, limit = 40): Article[] {
  const seen = new Set<string>();
  return lists
    .flat()
    .filter((a) => {
      const age = nowMs - Date.parse(a.publishedAt);
      return age <= maxAgeMs && age > -10 * 60_000;
    })
    .sort((a, b) => Date.parse(b.publishedAt) - Date.parse(a.publishedAt))
    .filter((a) => {
      const key = a.title.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
      if (seen.has(a.url) || seen.has(key)) return false;
      seen.add(a.url).add(key);
      return true;
    })
    .slice(0, limit);
}

/** Whether a story mentions the instrument by name or (distinctive) ticker. Yahoo's ticker feeds drift off-topic. */
export function mentions(article: Article, symbol: string, name?: string): boolean {
  const haystack = `${article.title} ${article.summary}`.toLowerCase();
  const escape = (term: string) => term.toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const terms = [name, symbol.length >= 3 ? symbol : undefined].filter((t): t is string => !!t?.trim());
  return terms.some((term) => new RegExp(`(^|[^a-z0-9])${escape(term)}([^a-z0-9]|$)`).test(haystack));
}

/**
 * Google News search terms: the instrument's name, plus the ticker when it's distinctive enough
 * (3+ characters) not to match ordinary words like "UP" or "AI".
 */
export function newsQuery(symbol: string, name?: string): string {
  const quote = (term: string) => `"${term.replaceAll('"', "").trim()}"`;
  const terms = new Set<string>();
  if (name && name.trim().toUpperCase() !== symbol.toUpperCase()) terms.add(quote(name));
  if (symbol.length >= 3 || terms.size === 0) terms.add(quote(symbol));
  return [...terms].join(" OR ");
}

const feeds = {
  yahoo: (tickers: string[]) => `https://feeds.finance.yahoo.com/rss/2.0/headline?s=${encodeURIComponent(tickers.join(","))}&region=US&lang=en-US`,
  googleSearch: (query: string) => `https://news.google.com/rss/search?q=${encodeURIComponent(`${query} when:2d`)}&hl=en-US&gl=US&ceid=US:en`,
  googleBusiness: "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en",
};

type Entry = { at: number; articles: Article[] };
type Fetch = typeof fetch;
export type NewsResponse = { articles: Article[]; fetchedAt: string; sources: { provider: Provider; ok: boolean }[] };

export function createNewsService({ ttlMs = 60_000, fetch: doFetch = fetch, now = Date.now }: { ttlMs?: number; fetch?: Fetch; now?: () => number } = {}) {
  const cache = new Map<string, Entry>();
  const inflight = new Map<string, Promise<Entry>>();

  async function load(url: string, provider: Provider): Promise<Entry> {
    const response = await doFetch(url, {
      headers: { "User-Agent": "Mozilla/5.0 (compatible; Iris/0.1)", Accept: "application/rss+xml, application/xml" },
      signal: AbortSignal.timeout(8000),
    });
    if (!response.ok) throw new Error(`${provider} answered ${response.status}`);
    return { at: now(), articles: parseRss(await response.text(), provider) };
  }

  /** Cached per feed URL; concurrent callers share one request, and failures fall back to the last good copy. */
  async function feed(url: string, provider: Provider): Promise<Entry> {
    const cached = cache.get(url);
    if (cached && now() - cached.at < ttlMs) return cached;
    let pending = inflight.get(url);
    if (!pending) {
      pending = load(url, provider).finally(() => inflight.delete(url));
      inflight.set(url, pending);
    }
    try {
      const fresh = await pending;
      cache.set(url, fresh);
      return fresh;
    } catch (error) {
      if (cached) return cached;
      throw error;
    }
  }

  async function collect(requests: [string, Provider][], maxAgeMs: number, keep: (a: Article) => boolean = () => true): Promise<NewsResponse> {
    const results = await Promise.allSettled(requests.map(([url, provider]) => feed(url, provider)));
    if (results.every((r) => r.status === "rejected")) throw new Error("No news source could be reached.");
    const ok = results.flatMap((r) => (r.status === "fulfilled" ? [r.value] : []));
    return {
      articles: mergeArticles(ok.map((e) => e.articles.filter(keep)), now(), maxAgeMs),
      fetchedAt: new Date(Math.min(...ok.map((e) => e.at))).toISOString(),
      sources: requests.map(([, provider], i) => ({ provider, ok: results[i].status === "fulfilled" })),
    };
  }

  return {
    // Yahoo answers unknown tickers with months-old generic stories, so asset news is capped at a week.
    asset: (symbol: string, name: string | undefined, assetClass: AssetClass) =>
      collect(
        [
          [feeds.yahoo([assetClass === "crypto" ? `${symbol}-USD` : symbol]), "Yahoo Finance"],
          [feeds.googleSearch(newsQuery(symbol, name)), "Google News"],
        ],
        7 * 24 * HOUR,
        // Google already searched by name; Yahoo's ticker feed needs checking.
        (a) => a.provider !== "Yahoo Finance" || mentions(a, symbol, name),
      ),
    markets: () =>
      collect(
        [
          [feeds.yahoo(["^GSPC", "^IXIC", "^DJI"]), "Yahoo Finance"],
          [feeds.googleBusiness, "Google News"],
        ],
        2 * 24 * HOUR,
      ),
  };
}

export function newsMiddleware(service = createNewsService()) {
  return async (req: IncomingMessage, res: ServerResponse, next: () => void) => {
    if (!req.url?.startsWith("/news/")) return next();
    const url = new URL(req.url, "http://local");
    const send = (status: number, body: unknown) => {
      res.statusCode = status;
      res.setHeader("Content-Type", "application/json");
      res.setHeader("Cache-Control", "no-store");
      res.end(JSON.stringify(body));
    };
    if (req.method !== "GET") return send(405, { message: "Only GET is supported." });
    try {
      if (url.pathname === "/news/markets") return send(200, await service.markets());
      if (url.pathname === "/news/asset") {
        const symbol = url.searchParams.get("symbol") ?? "";
        const name = url.searchParams.get("name")?.slice(0, 80) || undefined;
        const assetClass = url.searchParams.get("class") === "stock" ? "stock" : "crypto";
        if (!/^[A-Za-z0-9]{1,15}$/.test(symbol)) return send(400, { message: "Invalid symbol." });
        return send(200, await service.asset(symbol.toUpperCase(), name, assetClass));
      }
      return send(404, { message: "Unknown news endpoint." });
    } catch (error) {
      return send(502, { message: error instanceof Error ? error.message : "News is unavailable." });
    }
  };
}
