import type { Candle, Point } from "./tm";

export type Bar = { time: number; open: number; high: number; low: number; close: number };
type LinePoint = { time: number; value: number };

const seconds = (iso: string) => Math.floor(Date.parse(iso) / 1000);

/** API candles (string prices, oldest first) to finite, strictly ascending chart bars. */
export function toBars(candles: Candle[]): Bar[] {
  const bars: Bar[] = [];
  for (const candle of candles) {
    const bar = {
      time: seconds(candle.t),
      open: Number(candle.open),
      high: Number(candle.high),
      low: Number(candle.low),
      close: Number(candle.close),
    };
    if (![bar.time, bar.open, bar.high, bar.low, bar.close].every(Number.isFinite)) continue;
    const last = bars.at(-1);
    if (last && bar.time <= last.time) {
      if (bar.time === last.time) bars[bars.length - 1] = bar;
      continue;
    }
    bars.push(bar);
  }
  return bars;
}

export function toLine(points: Point[]): LinePoint[] {
  const line: LinePoint[] = [];
  for (const point of points) {
    const time = seconds(point.t);
    const value = Number(point.value);
    if (!Number.isFinite(time) || !Number.isFinite(value)) continue;
    if (line.length && time <= line[line.length - 1].time) continue;
    line.push({ time, value });
  }
  return line;
}

/**
 * Folds a live price into the bar series. Updates the bar whose bucket contains `atSeconds`,
 * or opens a new bar at that price. Ticks older than the last bar are ignored.
 */
export function applyTick(last: Bar | undefined, price: number, atSeconds: number, bucketSeconds: number): Bar | null {
  if (!last || !Number.isFinite(price) || price <= 0) return null;
  const time = Math.floor(atSeconds / bucketSeconds) * bucketSeconds;
  if (time < last.time) return null;
  if (time === last.time) {
    return { ...last, high: Math.max(last.high, price), low: Math.min(last.low, price), close: price };
  }
  return { time, open: price, high: price, low: price, close: price };
}
