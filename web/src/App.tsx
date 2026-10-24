import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Analyst } from "@/components/Analyst";
import { InstrumentHeader } from "@/components/InstrumentHeader";
import { Masthead } from "@/components/Masthead";
import { Movers } from "@/components/Movers";
import { NewsPanel } from "@/components/NewsPanel";
import { OrderFlow } from "@/components/OrderFlow";
import { OrderBook } from "@/components/OrderBook";
import { PointAndAsk } from "@/components/PointAndAsk";
import { Portfolio } from "@/components/Portfolio";
import { TradeTicket } from "@/components/TradeTicket";
import { OwlTips } from "@/components/OwlTips";
import { setMascotOn, useMascotOn } from "@/components/Mascot";
import { INDICATORS, PriceChart, type Indicators } from "@/components/PriceChart";
import { ReferencePanel } from "@/components/ReferencePanel";
import { Column, DeskGroup, ResizeHandle, Section } from "@/components/layout";
import { Panel, Segmented, Toggle } from "@/components/ui";
import { Tape, Watchlist } from "@/components/Watchlist";
import { useCatalog } from "@/hooks/useCatalog";
import { useStored } from "@/hooks/useStored";
import { TIMEFRAMES, type IndicatorKind } from "@/lib/tm";
import { Creators } from '@/components/Creators';

const DEFAULT_WATCHLIST = ["BTC", "ETH", "SOL", "HYPE", "XRP", "DOGE", "NVDA", "TSLA", "AAPL"];
const KnowledgeGraph = lazy(() => import("@/components/CompleteGraph").then(module => ({ default: module.CompleteGraph })));

const fromHash = () => decodeURIComponent(location.hash.slice(1)).toUpperCase() || "BTC";
const fromView = () => {
  const value = new URLSearchParams(location.search).get('view');
  return value === 'creators' || value === 'relationships' ? value : 'desk';
};

/** The selected symbol lives in the URL hash so a view can be linked to. */
function useSymbol() {
  const [symbol, setSymbol] = useState(fromHash);
  useEffect(() => {
    const onHash = () => setSymbol(fromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const select = useCallback((next: string) => {
    location.hash = encodeURIComponent(next);
  }, []);
  return [symbol, select] as const;
}

export default function App() {
  const catalog = useCatalog();
  const [symbol, select] = useSymbol();
  const [tfId, setTfId] = useStored("timeframe", "15m");
  const [indicators, setIndicators] = useStored<Indicators>("indicators", { sma: true, ema: false, bollinger: false, rsi: true, macd: false });
  const [watchlist, setWatchlist] = useStored("watchlist", DEFAULT_WATCHLIST);
  const tf = TIMEFRAMES.find((t) => t.id === tfId) ?? TIMEFRAMES[2];
  const cls = catalog.classOf(symbol);
  const hasPerp = catalog.perps.has(symbol);
  const starred = watchlist.includes(symbol);

  const [askOpen, setAskOpen] = useState(false);
  const [pointing, setPointing] = useState(false);
  const owlOn = useMascotOn();
  const [view, setView] = useState(fromView);
  const navigate = (next: 'desk' | 'creators' | 'relationships') => {
    setView(next);
    const url = new URL(location.href);
    if (next !== 'desk') url.searchParams.set('view', next);
    else url.searchParams.delete('view');
    url.searchParams.delete('video');
    history.pushState(null, '', url);
  };
  useEffect(() => {
    const onPop = () => setView(fromView());
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);
  const asset = catalog.bySymbol.get(symbol);
  const desk = {
    symbol,
    name: asset?.name,
    productClass: cls,
    assetClass: asset?.asset_class === "stock" ? ("stock" as const) : ("crypto" as const),
    chartTimeframe: tf.id,
    hasPerp,
  };

  useEffect(() => {
    document.title = `${view === 'creators' ? 'Creators' : symbol} · Iris`;
  }, [symbol, view]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "j" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setAskOpen((open) => !open);
      } else if (event.key === "Escape") setAskOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (view === 'relationships') return (
    <div className="flex h-full min-h-[720px] flex-col">
      <Masthead catalog={catalog} activeView="graph" onSelect={next => { select(next); navigate('desk'); }} onAsk={() => { navigate('desk'); setAskOpen(true); }} onGraph={() => navigate('relationships')} onCreators={() => navigate('creators')} onDesk={() => navigate('desk')} />
      <Suspense fallback={<div className="grid flex-1 place-items-center text-sm text-muted-foreground">Loading relationship graph…</div>}>
        <KnowledgeGraph initialSymbol={asset?.asset_class === 'crypto' || ['BTC','ETH','SOL','HYPE','XRP','DOGE'].includes(symbol) ? 'NVDA' : symbol} onClose={() => navigate('desk')} />
      </Suspense>
    </div>
  );

  if (view === 'creators') return <Creators catalog={catalog} onDesk={next => { select(next); navigate('desk'); }}/>;

  return (
    <div className="flex h-full min-h-[720px] flex-col">
      <Masthead catalog={catalog} onSelect={select} onAsk={() => setAskOpen(true)} onGraph={() => navigate('relationships')} onCreators={() => navigate('creators')} onDesk={() => navigate('desk')} onPoint={() => setPointing((on) => !on)} pointing={pointing} />
      <Tape symbols={watchlist} catalog={catalog} onSelect={select} />
      <DeskGroup id="columns" orientation="horizontal" className="flex-1">
        <Column id="left" defaultSize={250} minSize={190} maxSize={420} fixed className="bg-sidebar/40">
          <DeskGroup id="left-v2" orientation="vertical">
            <Section id="portfolio" defaultSize="36%">
              <Portfolio onSelect={select} />
            </Section>
            <ResizeHandle orientation="vertical" />
            <Section id="watchlist" defaultSize="36%">
              <Watchlist
                symbols={watchlist}
                selected={symbol}
                catalog={catalog}
                onSelect={select}
                onRemove={(s) => setWatchlist((list) => list.filter((item) => item !== s))}
              />
            </Section>
            <ResizeHandle orientation="vertical" />
            <Section id="movers" defaultSize="28%">
              <Movers catalog={catalog} onSelect={select} />
            </Section>
          </DeskGroup>
        </Column>
        <ResizeHandle orientation="horizontal" />
        <Column id="main" minSize={420}>
          <DeskGroup id="main" orientation="vertical">
            <Section id="overview" defaultSize="25%" minSize={110}>
              <Panel title="Overview">
                <InstrumentHeader
                  symbol={symbol}
                  cls={cls}
                  asset={asset}
                  hasPerp={hasPerp}
                  starred={starred}
                  onStar={() => setWatchlist((list) => (starred ? list.filter((s) => s !== symbol) : [...list, symbol]))}
                />
              </Panel>
            </Section>
            <ResizeHandle orientation="vertical" />
            <Section id="chart" defaultSize="43%" minSize={220}>
              <Panel title="Chart" meta={`${symbol} · ${tf.id}`} delay={60}>
                <div className="flex flex-wrap items-center gap-2 border-b px-5 py-2">
                  <Segmented label="Timeframe" options={TIMEFRAMES.map((t) => ({ id: t.id, label: t.id, title: `${t.resolution} candles over ${t.window}` }))} value={tf.id} onChange={setTfId} />
                  <span className="mx-1 h-4 w-px bg-border" />
                  {(Object.keys(INDICATORS) as IndicatorKind[]).map((kind) => (
                    <Toggle key={kind} pressed={indicators[kind]} onClick={() => setIndicators((s) => ({ ...s, [kind]: !s[kind] }))}>
                      {INDICATORS[kind].label}
                    </Toggle>
                  ))}
                </div>
                <PriceChart symbol={symbol} cls={cls} tf={tf} indicators={indicators} />
              </Panel>
            </Section>
            <ResizeHandle orientation="vertical" />
            <Section id="order-flow" defaultSize="32%" minSize={150}>
              <Panel title="Order flow" meta="Perp · taker volume" delay={120}>
                <div className="min-h-0 flex-1">
                  <OrderFlow symbol={symbol} hasPerp={hasPerp} />
                </div>
              </Panel>
            </Section>
          </DeskGroup>
        </Column>
        <ResizeHandle orientation="horizontal" />
        <Column id="right" defaultSize={340} minSize={260} maxSize={560} fixed className="bg-sidebar/40">
          <DeskGroup id="right-v3" orientation="vertical">
            <Section id="trade" defaultSize="46%" minSize={120}>
              <TradeTicket symbol={symbol} />
            </Section>
            <ResizeHandle orientation="vertical" />
            <Section id="order-book" defaultSize="22%">
              <OrderBook symbol={symbol} hasPerp={hasPerp} />
            </Section>
            <ResizeHandle orientation="vertical" />
            <Section id="reference" defaultSize="10%">
              <ReferencePanel symbol={symbol} />
            </Section>
            <ResizeHandle orientation="vertical" />
            <Section id="news" defaultSize="22%" minSize={140}>
              <NewsPanel
                symbol={symbol}
                name={asset?.name}
                assetClass={asset?.asset_class === "stock" ? "stock" : "crypto"}
                catalogReady={catalog.all.length > 0}
              />
            </Section>
          </DeskGroup>
        </Column>
      </DeskGroup>
      <Analyst open={askOpen} onClose={() => setAskOpen(false)} context={desk} />
      <PointAndAsk picking={pointing} onPickingChange={setPointing} context={desk} />
      <OwlTips />
      <footer className="flex flex-wrap items-center gap-x-4 border-t px-5 py-1.5 text-[10px] text-muted-foreground">
        <span>Orders go to your True Markets account and move real funds.</span>
        <button onClick={() => setMascotOn(!owlOn)} className="hover:text-foreground" title="Show or hide the Iris Owl across the app">
          {owlOn ? "Hide owl" : "Show owl"}
        </button>
        <span className="ml-auto">Charts by TradingView Lightweight Charts™. Not investment advice.</span>
      </footer>
    </div>
  );
}
