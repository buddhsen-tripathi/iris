import { describe, expect, it } from "vitest";
import { applyTick, toBars, toLine } from "./candles";

const candle = (t: string, close: string) => ({ t, open: close, high: close, low: close, close });

describe("toBars", () => {
  it("parses string prices into ascending second timestamps", () => {
    const bars = toBars([candle("2026-10-24T15:00:00Z", "81584.7"), candle("2026-10-24T16:00:00Z", "81616.9")]);
    expect(bars).toEqual([
      { time: 1792854000, open: 81584.7, high: 81584.7, low: 81584.7, close: 81584.7 },
      { time: 1792857600, open: 81616.9, high: 81616.9, low: 81616.9, close: 81616.9 },
    ]);
  });

  it("drops non-finite rows, keeps the later duplicate, and skips out-of-order rows", () => {
    const bars = toBars([
      candle("2026-10-24T15:00:00Z", "1"),
      candle("2026-10-24T15:00:00Z", "2"),
      candle("2026-10-24T14:00:00Z", "3"),
      candle("2026-10-24T16:00:00Z", "NaN"),
    ]);
    expect(bars.map((b) => b.close)).toEqual([2]);
  });
});

describe("toLine", () => {
  it("skips invalid and non-ascending points", () => {
    const line = toLine([
      { t: "2026-10-24T15:00:00Z", value: "44.5" },
      { t: "2026-10-24T15:00:00Z", value: "45" },
      { t: "2026-10-24T16:00:00Z", value: "x" },
    ]);
    expect(line).toEqual([{ time: 1792854000, value: 44.5 }]);
  });
});

describe("applyTick", () => {
  const last = { time: 900, open: 10, high: 12, low: 9, close: 11 };

  it("extends the current bucket", () => {
    expect(applyTick(last, 13, 1000, 900)).toEqual({ time: 900, open: 10, high: 13, low: 9, close: 13 });
    expect(applyTick(last, 8, 1799, 900)).toEqual({ time: 900, open: 10, high: 12, low: 8, close: 8 });
  });

  it("opens a new bar at the tick price when the bucket rolls over", () => {
    expect(applyTick(last, 11.5, 1800, 900)).toEqual({ time: 1800, open: 11.5, high: 11.5, low: 11.5, close: 11.5 });
  });

  it("ignores stale ticks, bad prices, and empty series", () => {
    expect(applyTick(last, 11, 899, 900)).toBeNull();
    expect(applyTick(last, Number.NaN, 1000, 900)).toBeNull();
    expect(applyTick(last, 0, 1000, 900)).toBeNull();
    expect(applyTick(undefined, 11, 1000, 900)).toBeNull();
  });
});
