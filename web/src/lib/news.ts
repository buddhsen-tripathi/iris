// Live headlines via the dev server's /news endpoint (server/news.ts): Yahoo Finance + Google News RSS.
import type { NewsResponse } from "../../server/news";
import type { SentimentRead } from "../../server/sentiment";

export type { SentimentRead } from "../../server/sentiment";

/** AI read of the latest 10 headlines; the server reuses a stored read when the headlines are unchanged unless forced. */
export async function analyzeNews(body: { symbol: string; name?: string; assetClass: "crypto" | "stock"; force?: boolean }, signal?: AbortSignal): Promise<SentimentRead> {
  const response = await fetch("/ai/news-sentiment", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message ?? `Analysis failed (${response.status})`);
  return data as SentimentRead;
}


export async function fetchNews(path: string, signal?: AbortSignal): Promise<NewsResponse> {
  const response = await fetch(path, { signal });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.message ?? response.statusText);
  return body as NewsResponse;
}
