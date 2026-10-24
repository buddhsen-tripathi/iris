import { useQueries, useQuery } from "@tanstack/react-query";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type LineWidth,
  type MouseEventParams,
  type SeriesType,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTopic } from "@/hooks/useMarket";
import { useTheme } from "@/hooks/useTheme";
import { applyTick, toBars, toLine, type Bar } from "@/lib/candles";
import { cssVar } from "@/lib/color";
import { decimalsFor, pct, price } from "@/lib/format";
import { TmError, tm, topics, type IndicatorKind, type LivePrice, type ProductClass, type Timeframe } from "@/lib/tm";
import { cn } from "@/lib/utils";

export type Indicators = Record<IndicatorKind, boolean>;

type LineStyleSpec = { color: string; alpha?: number; width?: LineWidth; style?: LineStyle; histogram?: boolean };

// Overlays share the price pane; oscillators each get their own pane below it.
export const INDICATORS: Record<IndicatorKind, { label: string; period?: number; pane: boolean; lines: Record<string, LineStyleSpec> }> = {
  sma: { label: "SMA 20", period: 20, pane: false, lines: { sma: { color: "--chart-3", width: 2 } } },
  ema: { label: "EMA 50", period: 50, pane: false, lines: { ema: { color: "--chart-1", alpha: 0.85, width: 1 } } },
  bollinger: {
    label: "BB 20·2",
    pane: false,
    lines: {
      upper: { color: "--chart-4", width: 1, style: LineStyle.Dashed },
      middle: { color: "--chart-4", alpha: 0.7, width: 1, style: LineStyle.Dotted },
      lower: { color: "--chart-4", width: 1, style: LineStyle.Dashed },
    },
  },
  rsi: { label: "RSI 14", period: 14, pane: true, lines: { rsi: { color: "--chart-2", width: 1 } } },
  macd: {
    label: "MACD 12·26·9",
    pane: true,
    lines: {
      histogram: { color: "--chart-3", histogram: true },
      macd: { color: "--chart-2", width: 1 },
      signal: { color: "--chart-1", width: 1 },
    },
  },
};

const ts = (time: number) => time as UTCTimestamp;

/** Spot listings load OHLC candles; perp-only listings load price samples drawn as a line. */
async function loadSeries(symbol: string, cls: ProductClass, tf: Timeframe, signal: AbortSignal): Promise<{ mode: "ohlc" | "line"; bars: Bar[] }> {
  if (cls === "spot") return { mode: "ohlc", bars: toBars((await tm.candles(symbol, tf, signal)).candles) };
  const { points } = await tm.priceHistory(symbol, tf, cls, signal);
  const line = toLine(points.map((point) => ({ t: point.t, value: point.price })));
  return { mode: "line", bars: line.map(({ time, value }) => ({ time, open: value, high: value, low: value, close: value })) };
}
const asCandles = (bars: Bar[]) => bars.map((bar) => ({ ...bar, time: ts(bar.time) })) as CandlestickData<UTCTimestamp>[];

function chartOptions(tf: Timeframe) {
  const grid = cssVar("--border", 0.5);
  const crosshair = { color: cssVar("--foreground", 0.35), width: 1 as LineWidth, style: LineStyle.Dashed, labelBackgroundColor: cssVar("--primary") };
  return {
    layout: {
      background: { type: ColorType.Solid, color: "transparent" },
      textColor: cssVar("--muted-foreground"),
      fontFamily: "Geist Mono Variable, Geist Mono, ui-monospace, monospace",
      fontSize: 11,
      panes: { separatorColor: cssVar("--border"), separatorHoverColor: cssVar("--muted", 0.6), enableResize: true },
    },
    grid: { vertLines: { color: grid }, horzLines: { color: grid } },
    crosshair: { mode: CrosshairMode.Normal, vertLine: crosshair, horzLine: crosshair },
    rightPriceScale: { borderColor: cssVar("--border"), scaleMargins: { top: 0.12, bottom: 0.08 } },
    timeScale: { borderColor: cssVar("--border"), timeVisible: tf.seconds < 86400, secondsVisible: false, rightOffset: 6 },
  };
}

function candleColors() {
  const up = cssVar("--up");
  const down = cssVar("--down");
  return { upColor: up, borderUpColor: up, wickUpColor: up, downColor: down, borderDownColor: down, wickDownColor: down };
}

export function PriceChart({ symbol, cls, tf, indicators }: { symbol: string; cls: ProductClass; tf: Timeframe; indicators: Indicators }) {
  const container = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const candles = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const line = useRef<ISeriesApi<"Line"> | null>(null);
  const overlays = useRef<ISeriesApi<SeriesType>[]>([]);
  const bars = useRef<Bar[]>([]);
  const loadedKey = useRef<string | null>(null);
  const [hover, setHover] = useState<Bar | null>(null);
  const [lastBar, setLastBar] = useState<Bar | null>(null);
  const { theme } = useTheme();
  const key = `${symbol}:${cls}:${tf.id}`;

  const history = useQuery({
    queryKey: ["series", symbol, cls, tf.id],
    queryFn: ({ signal }) => loadSeries(symbol, cls, tf, signal),
    // Live ticks extend the last bar between refetches; refetching reconciles with trade-built candles.
    refetchInterval: 60_000,
    retry: (count, error) => !(error instanceof TmError && error.status < 500) && count < 2,
  });

  const enabled = useMemo(() => (Object.keys(INDICATORS) as IndicatorKind[]).filter((kind) => indicators[kind]), [indicators]);
  const studies = useQueries({
    queries: enabled.map((kind) => ({
      queryKey: ["indicator", symbol, cls, tf.id, kind],
      queryFn: ({ signal }: { signal: AbortSignal }) => tm.indicator(symbol, cls, tf, kind, INDICATORS[kind].period, signal),
      refetchInterval: 60_000,
      enabled: history.isSuccess,
    })),
  });
  const studiesVersion = studies.map((study) => study.dataUpdatedAt).join(",");

  // Create the chart once.
  useEffect(() => {
    if (!container.current) return;
    const instance = createChart(container.current, { autoSize: true, ...chartOptions(tf) });
    candles.current = instance.addSeries(CandlestickSeries, { ...candleColors(), priceLineStyle: LineStyle.Dotted });
    line.current = instance.addSeries(LineSeries, { color: cssVar("--foreground"), lineWidth: 2, priceLineStyle: LineStyle.Dotted });
    const onMove = (param: MouseEventParams) => {
      const bar = candles.current && (param.seriesData.get(candles.current) as Bar | undefined);
      const point = line.current && (param.seriesData.get(line.current) as { time: number; value: number } | undefined);
      if (bar && "open" in bar) setHover(bar);
      else if (point && "value" in point) setHover({ time: point.time, open: point.value, high: point.value, low: point.value, close: point.value });
      else setHover(null);
    };
    instance.subscribeCrosshairMove(onMove);
    chart.current = instance;
    return () => {
      instance.unsubscribeCrosshairMove(onMove);
      instance.remove();
      chart.current = candles.current = line.current = null;
      overlays.current = [];
      loadedKey.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Theme and timeframe styling.
  useEffect(() => {
    chart.current?.applyOptions(chartOptions(tf));
    candles.current?.applyOptions(candleColors());
    line.current?.applyOptions({ color: cssVar("--foreground") });
  }, [theme, tf]);

  // History.
  const mode = history.data?.mode;
  useEffect(() => {
    if (!candles.current || !line.current || !chart.current) return;
    if (!history.data) {
      if (loadedKey.current !== key) {
        candles.current.setData([]);
        line.current.setData([]);
        bars.current = [];
        setLastBar(null);
      }
      return;
    }
    const next = history.data.bars;
    const timeScale = chart.current.timeScale();
    const keep = loadedKey.current === key ? timeScale.getVisibleLogicalRange() : null;
    bars.current = [...next];
    // One precision for the whole axis, from the latest price, so labels near zero don't sprout decimals.
    const decimals = decimalsFor(next.at(-1)?.close ?? 0);
    const priceFormat = { type: "custom" as const, minMove: 10 ** -decimals, formatter: (value: number) => price(value, decimals) };
    // Both series share the price scale, which formats with the first series, so keep them in step.
    candles.current.applyOptions({ priceFormat });
    line.current.applyOptions({ priceFormat });
    if (history.data.mode === "ohlc") {
      line.current.setData([]);
      candles.current.setData(asCandles(next));
    } else {
      candles.current.setData([]);
      line.current.setData(next.map((bar) => ({ time: ts(bar.time), value: bar.close })));
    }
    if (keep) timeScale.setVisibleLogicalRange(keep);
    else timeScale.setVisibleLogicalRange({ from: Math.max(0, next.length - 140), to: next.length + 6 });
    loadedKey.current = key;
    setLastBar(next.at(-1) ?? null);
  }, [history.data, key]);

  // Live ticks.
  const live = useTopic<LivePrice>(topics.price(symbol, cls)).value;
  useEffect(() => {
    if (!live || loadedKey.current !== key || !candles.current || !line.current) return;
    const bar = applyTick(bars.current.at(-1), Number(live.data.price), Date.parse(live.data.timestamp) / 1000, tf.seconds);
    if (!bar) return;
    const last = bars.current.at(-1);
    if (last && last.time === bar.time) bars.current[bars.current.length - 1] = bar;
    else bars.current.push(bar);
    if (mode === "line") line.current.update({ time: ts(bar.time), value: bar.close });
    else candles.current.update({ ...bar, time: ts(bar.time) });
    setLastBar(bar);
  }, [live, key, tf.seconds, mode]);

  // Indicators: rebuilt whenever the selection, data, or theme changes.
  useEffect(() => {
    const instance = chart.current;
    if (!instance) return;
    for (const series of overlays.current) instance.removeSeries(series);
    overlays.current = [];
    for (let index = instance.panes().length - 1; index > 0; index--) instance.removePane(index);

    // MACD is in price units, so it needs the instrument's precision; RSI is 0–100.
    const macdDecimals = Math.min(10, decimalsFor(bars.current.at(-1)?.close ?? 0) + 1);
    const oscillatorFormat = (kind: IndicatorKind) => {
      const precision = kind === "macd" ? macdDecimals : 2;
      return { type: "price" as const, precision, minMove: 10 ** -precision };
    };
    let pane = 0;
    enabled.forEach((kind, i) => {
      const spec = INDICATORS[kind];
      const data = studies[i]?.data;
      if (!data) return;
      const paneIndex = spec.pane ? ++pane : 0;
      for (const [line, style] of Object.entries(spec.lines)) {
        const points = toLine(data.lines[line] ?? []).map((point) => ({ ...point, time: ts(point.time) }));
        if (!points.length) continue;
        const common = { priceLineVisible: false, lastValueVisible: spec.pane, crosshairMarkerVisible: !style.histogram };
        if (style.histogram) {
          const up = cssVar("--up", 0.35);
          const down = cssVar("--down", 0.55);
          const series = instance.addSeries(HistogramSeries, { ...common, priceFormat: oscillatorFormat(kind) }, paneIndex);
          series.setData(points.map((point) => ({ ...point, color: point.value >= 0 ? up : down })));
          overlays.current.push(series);
        } else {
          const series = instance.addSeries(
            LineSeries,
            {
              ...common,
              color: cssVar(style.color, style.alpha),
              lineWidth: style.width ?? 1,
              lineStyle: style.style ?? LineStyle.Solid,
              ...(spec.pane && { priceFormat: oscillatorFormat(kind) }),
            },
            paneIndex,
          );
          series.setData(points);
          if (kind === "rsi") {
            for (const level of [70, 30])
              series.createPriceLine({ price: level, color: cssVar("--muted-foreground", 0.6), lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "" });
          }
          overlays.current.push(series);
        }
      }
    });
    instance.panes().forEach((p, index) => p.setStretchFactor(index === 0 ? 4 : 1));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, studiesVersion, theme]);

  const shown = hover ?? lastBar;
  const change = shown ? (shown.close / shown.open - 1) * 100 : undefined;
  const error = history.error;

  return (
    <div className="relative min-h-0 flex-1" data-ask-scope="Price chart">
      <div ref={container} className="absolute inset-0" />
      <div className="pointer-events-none absolute top-2 left-3 z-10 flex flex-col gap-1">
        <div className="num flex flex-wrap items-baseline gap-x-3 text-[11px] text-muted-foreground">
          <span className="font-sans font-semibold text-foreground">
            {symbol}
            {cls === "perp" && "-PERP"} · {tf.id} · UTC
          </span>
          {shown && mode === "line" && (
            <>
              <span>
                Price <b className="font-medium text-foreground">{price(shown.close)}</b>
              </span>
              <span className="font-sans">perp price sampled every {tf.resolution}; no OHLC candles for this source</span>
            </>
          )}
          {shown && mode === "ohlc" && (
            <>
              <span>
                O <b className="font-medium text-foreground">{price(shown.open)}</b>
              </span>
              <span>
                H <b className="font-medium text-foreground">{price(shown.high)}</b>
              </span>
              <span>
                L <b className="font-medium text-foreground">{price(shown.low)}</b>
              </span>
              <span>
                C <b className="font-medium text-foreground">{price(shown.close)}</b>
              </span>
              <span className={cn(change && change > 0 && "text-up", change && change < 0 && "text-down")}>{pct(change)}</span>
            </>
          )}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {enabled.map((kind, i) => (
            <span key={kind} className="num flex items-center gap-1 rounded-sm bg-card/80 px-1.5 py-0.5 text-[10px] text-muted-foreground">
              <i className="inline-block h-0.5 w-3" style={{ background: `var(${Object.values(INDICATORS[kind].lines).at(-1)!.color})` }} />
              {INDICATORS[kind].label}
              {studies[i]?.isError && <span className="text-down"> unavailable</span>}
            </span>
          ))}
        </div>
      </div>
      {(history.isPending || error) && (
        <div className="absolute inset-0 z-10 grid place-items-center">
          <p className="max-w-sm px-6 text-center text-sm text-muted-foreground">
            {!error ? "Loading…" : error instanceof TmError && error.status === 400 ? `No trade-built candles for ${symbol}.` : "Candles are unavailable."}
            {error && <span className="kicker mt-2 block">{error.message}</span>}
          </p>
        </div>
      )}
    </div>
  );
}
