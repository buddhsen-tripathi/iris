import { describe, expect, it, vi } from "vitest";
import { createNewsService, mentions, mergeArticles, newsQuery, parseRss, type Article } from "./news";

// Fixtures mirror the shape of the real feeds (checked 2026-10-24).
const yahooXml = `<?xml version="1.0"?><rss version="2.0"><channel><title>Yahoo! Finance: BTC-USD News</title>
<item><description>Crypto traders ask &lt;b&gt;again&lt;/b&gt;</description><guid>1</guid><link>https://247wallst.com/a</link><pubDate>Sat, 24 Oct 2026 16:03:29 +0000</pubDate><title>Is Bitcoin Dead? CZ &amp; the &#8220;best&#8221; times</title></item>
<item><link>javascript:alert(1)</link><pubDate>Sat, 24 Oct 2026 16:00:00 +0000</pubDate><title>Bad link</title></item>
<item><link>https://finance.yahoo.com/b</link><pubDate>not a date</pubDate><title>Undated</title></item>
</channel></rss>`;
const googleXml = `<rss version="2.0"><channel>
<item><title>Bitcoin falls below $80,000 - CoinDesk</title><link>https://news.google.com/rss/articles/x</link><pubDate>Sat, 24 Oct 2026 15:17:13 GMT</pubDate><source url="https://www.coindesk.com">CoinDesk</source></item>
</channel></rss>`;

const at = (iso: string, over: Partial<Article> = {}): Article => ({
  title: "t",
  summary: "",
  url: `https://x.com/${iso}`,
  source: "s",
  publishedAt: iso,
  provider: "Google News",
  ...over,
});

describe("parseRss", () => {
  it("normalises Yahoo items, decoding entities and naming the publisher from the link", () => {
    expect(parseRss(yahooXml, "Yahoo Finance")).toEqual([
      {
        title: "Is Bitcoin Dead? CZ & the “best” times",
        summary: "Crypto traders ask again",
        url: "https://247wallst.com/a",
        source: "247wallst.com",
        publishedAt: "2026-10-24T16:03:29.000Z",
        provider: "Yahoo Finance",
      },
    ]);
  });

  it("uses Google's <source> and strips the publisher suffix from titles", () => {
    const [article] = parseRss(googleXml, "Google News");
    expect(article.title).toBe("Bitcoin falls below $80,000");
    expect(article.source).toBe("CoinDesk");
  });

  it("tolerates empty or non-RSS bodies", () => {
    expect(parseRss("<rss><channel></channel></rss>", "Google News")).toEqual([]);
    expect(parseRss("<html></html>", "Google News")).toEqual([]);
  });
});

describe("mergeArticles", () => {
  const now = Date.parse("2026-10-24T16:00:00Z");
  it("sorts newest first, drops old or future items, and removes repeated headlines", () => {
    const merged = mergeArticles(
      [
        [at("2026-10-24T15:00:00Z", { title: "Bitcoin slides!" }), at("2026-10-10T00:00:00Z", { title: "Old" })],
        [at("2026-10-24T15:30:00Z", { title: "bitcoin slides" }), at("2026-10-24T17:00:00Z", { title: "Future" }), at("2026-10-24T14:00:00Z", { title: "Other" })],
      ],
      now,
      7 * 86_400_000 - 1,
    );
    expect(merged.map((a) => a.title)).toEqual(["bitcoin slides", "Other"]);
  });
});

describe("mentions", () => {
  it("matches the name or a distinctive ticker as a whole word, in the title or summary", () => {
    expect(mentions(at("2026-10-24T00:00:00Z", { title: "Nvidia earnings preview" }), "NVDA", "NVIDIA")).toBe(true);
    expect(mentions(at("2026-10-24T00:00:00Z", { title: "Chip stocks", summary: "Shares of NVDA rose" }), "NVDA", "NVIDIA")).toBe(true);
    expect(mentions(at("2026-10-24T00:00:00Z", { title: "Could Redwire Be the Next Rocket Lab?" }), "NVDA", "NVIDIA")).toBe(false);
    expect(mentions(at("2026-10-24T00:00:00Z", { title: "Markets look up" }), "UP", "Superform")).toBe(false);
    expect(mentions(at("2026-10-24T00:00:00Z", { title: "S&P (SPX) rallies" }), "SPX", "SPX6900")).toBe(true);
  });
});

describe("newsQuery", () => {
  it("combines names with distinctive tickers only", () => {
    expect(newsQuery("BTC", "Bitcoin")).toBe('"Bitcoin" OR "BTC"');
    expect(newsQuery("UP", "Superform")).toBe('"Superform"');
    expect(newsQuery("XRP", "XRP")).toBe('"XRP"');
    expect(newsQuery("AI")).toBe('"AI"');
  });
});

describe("news service", () => {
  const rss = (xml: string) => new Response(xml, { status: 200 });

  it("queries Yahoo by ticker and Google by name, then merges", async () => {
    const fetch = vi.fn(async (url: string) => rss(url.includes("yahoo") ? yahooXml : googleXml));
    const service = createNewsService({ fetch: fetch as unknown as typeof globalThis.fetch, now: () => Date.parse("2026-10-24T16:10:00Z") });
    const result = await service.asset("BTC", "Bitcoin", "crypto");
    const urls = fetch.mock.calls.map(([url]) => decodeURIComponent(url));
    expect(urls[0]).toContain("s=BTC-USD");
    expect(urls[1]).toContain('q="Bitcoin" OR "BTC" when:2d');
    expect(result.articles.map((a) => a.provider)).toEqual(["Yahoo Finance", "Google News"]);
    expect(result.sources.every((s) => s.ok)).toBe(true);
    await service.asset("NVDA", "NVIDIA", "stock");
    expect(decodeURIComponent(fetch.mock.calls[2][0])).toContain("s=NVDA&");
  });

  it("caches per feed, shares in-flight requests, and falls back to the last good copy", async () => {
    let now = Date.parse("2026-10-24T16:10:00Z");
    const fetch = vi.fn(async () => rss(googleXml));
    const service = createNewsService({ ttlMs: 60_000, fetch: fetch as unknown as typeof globalThis.fetch, now: () => now });
    await Promise.all([service.markets(), service.markets()]);
    expect(fetch).toHaveBeenCalledTimes(2);
    now += 61_000;
    fetch.mockRejectedValue(new Error("offline"));
    const stale = await service.markets();
    expect(stale.articles).toHaveLength(1);
  });

  it("reports partial outages and fails only when every source is down", async () => {
    const fetch = vi.fn(async (url: string) => (url.includes("yahoo") ? new Response("", { status: 503 }) : rss(googleXml)));
    const service = createNewsService({ fetch: fetch as unknown as typeof globalThis.fetch, now: () => Date.parse("2026-10-24T16:10:00Z") });
    expect((await service.markets()).sources).toEqual([
      { provider: "Yahoo Finance", ok: false },
      { provider: "Google News", ok: true },
    ]);
    const down = createNewsService({ fetch: vi.fn().mockRejectedValue(new Error("x")) });
    await expect(down.markets()).rejects.toThrow("No news source");
  });
});
