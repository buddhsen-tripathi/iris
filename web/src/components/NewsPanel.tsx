import { useQuery } from "@tanstack/react-query";
import { getAiConfig } from "@/lib/ai";
import { ExternalLink } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNow } from "@/hooks/useMarket";
import { age } from "@/lib/format";
import { analyzeNews, fetchNews } from "@/lib/news";
import { cn } from "@/lib/utils";
import { SentimentSummary, TONE, signed } from "./NewsSentiment";
import { Empty, Panel, Segmented } from "./ui";

type Tab = "asset" | "markets";

// The server caches each feed for 60s, so this is as fresh as polling gets.
const POLL_MS = 60_000;

export function NewsPanel({
  symbol,
  name,
  assetClass,
  catalogReady,
}: {
  symbol: string;
  name?: string;
  assetClass: "crypto" | "stock";
  /** Name and asset class are only final once the catalog has loaded; analysing earlier would score a different feed. */
  catalogReady: boolean;
}) {
  const [tab, setTab] = useState<Tab>("asset");
  const now = useNow(15_000);

  // The AI read of the instrument's headlines runs every time its tab is opened (a new run number)
  // and on every instrument change (the symbol is in the key; gcTime 0 drops reads nobody shows).
  const [run, setRun] = useState({ n: 0, force: false });
  const openTab = (next: Tab) => {
    if (next === "asset" && tab !== "asset") setRun((r) => ({ n: r.n + 1, force: false }));
    setTab(next);
  };
  const ai = useQuery({ queryKey: ["ai-config"], queryFn: getAiConfig, staleTime: Infinity });
  const read = useQuery({
    queryKey: ["news-sentiment", symbol, name, assetClass, run.n, run.force],
    queryFn: ({ signal }) => analyzeNews({ symbol, name, assetClass, force: run.force }, signal),
    enabled: tab === "asset" && catalogReady && ai.data?.enabled === true,
    staleTime: Infinity,
    gcTime: 0,
    retry: false,
  });
  const path =
    tab === "markets" ? "/news/markets" : `/news/asset?${new URLSearchParams({ symbol, class: assetClass, ...(name && { name }) })}`;
  const news = useQuery({
    queryKey: ["news", path],
    queryFn: ({ signal }) => fetchNews(path, signal),
    refetchInterval: POLL_MS,
  });

  // Mark stories that arrive after this feed first loaded.
  const seen = useRef<{ path: string; urls: Set<string> } | null>(null);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  useEffect(() => {
    const articles = news.data?.articles;
    if (!articles) return;
    if (seen.current?.path !== path) {
      seen.current = { path, urls: new Set(articles.map((a) => a.url)) };
      setFresh(new Set());
      return;
    }
    const added = articles.filter((a) => !seen.current!.urls.has(a.url)).map((a) => a.url);
    added.forEach((url) => seen.current!.urls.add(url));
    if (added.length) setFresh((previous) => new Set([...previous, ...added]));
  }, [news.data, path]);

  const articles = news.data?.articles ?? [];
  // Per-headline AI scores for the instrument tab, matched by URL; newer headlines stay unscored until the next read.
  const scores = tab === "asset" && read.data ? new Map(read.data.items.map((item) => [item.url, item])) : undefined;
  const down = news.data?.sources.filter((s) => !s.ok).map((s) => s.provider) ?? [];

  const headlines = (
    <>
      {down.length > 0 && <p className="kicker px-4 pt-2 tracking-normal normal-case">Some news sources are unavailable; showing the rest</p>}
      {news.isError ? (
        <Empty>{news.error.message}</Empty>
      ) : news.isPending ? (
        <Empty>Loading headlines…</Empty>
      ) : articles.length === 0 ? (
        <Empty>No headlines about {name ?? symbol} in the past few days.</Empty>
      ) : (
        <ol className="scroll-thin min-h-0 flex-1 overflow-y-auto py-1">
          {articles.map((article) => {
            const score = scores?.get(article.url);
            const tone = score ? TONE[score.label] : undefined;
            return (
              <li key={article.url}>
                <a
                  href={article.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={`${article.source} via ${article.provider}${score ? ` · AI: ${tone!.label.toLowerCase()} ${signed(score.score)}` : ""}`}
                  className="group grid grid-cols-[3px_minmax(0,1fr)] gap-x-2.5 border-b border-border/50 px-4 py-2.5 hover:bg-accent/60"
                >
                  <span className={cn("rounded-full transition-colors duration-500", tone ? tone.bar : "bg-transparent")} aria-hidden />
                  <span className="min-w-0">
                    <span className="kicker flex items-center gap-1.5 tracking-normal normal-case">
                      {fresh.has(article.url) && <span className="size-1.5 shrink-0 rounded-full bg-chart-1" title="New since you opened this feed" />}
                      <span className="truncate font-semibold">{article.source}</span>
                      <span className="num shrink-0 font-normal">{age(Date.parse(article.publishedAt), now)}</span>
                      <ExternalLink className="size-3 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
                      {score && (
                        <span className={cn("num ml-auto shrink-0 rounded-sm px-1 text-[10.5px]", tone!.text, tone!.tint)} aria-label={`AI ${tone!.label} ${signed(score.score)}`}>
                          {signed(score.score)}
                        </span>
                      )}
                    </span>
                    <span className={cn("mt-0.5 line-clamp-2 text-[12.5px] leading-snug", fresh.has(article.url) && "font-medium")}>{article.title}</span>
                    {score && <span className={cn("mt-0.5 block truncate text-[10.5px]", tone!.text)}>{score.reason}</span>}
                  </span>
                </a>
              </li>
            );
          })}
        </ol>
      )}
    </>
  );

  return (
    <Panel
      title="Live news"
      meta={news.data ? `updated ${age(Date.parse(news.data.fetchedAt), now)} ago` : undefined}
      delay={260}
    >
      <div className="flex items-center gap-2 px-4 pt-2 [&>div]:flex-1 [&_button]:flex-1">
        <Segmented
          label="News feed"
          options={[
            { id: "asset", label: symbol, title: `Headlines about ${name ?? symbol}, with an AI read of the latest 10` },
            { id: "markets", label: "Markets", title: "Market and business headlines" },
          ]}
          value={tab}
          onChange={openTab}
        />
      </div>
      {tab === "asset" && (
        <SentimentSummary read={read} symbol={symbol} enabled={ai.data?.enabled} onReanalyze={() => setRun((r) => ({ n: r.n + 1, force: true }))} />
      )}
      {headlines}
    </Panel>
  );
}
