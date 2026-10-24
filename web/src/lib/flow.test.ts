import { describe, expect, it } from "vitest";
import { insertPrints, largeTradeThreshold, shareSeries, summarize, toPrint, type Print } from "./flow";

const print = (tid: number, time: number, side: "buy" | "sell", notional: number): Print => ({ tid, time, side, px: notional, sz: 1, notional });

describe("toPrint", () => {
  it("maps Hyperliquid aggressor sides and rejects bad rows", () => {
    expect(toPrint({ coin: "BTC", side: "B", px: "79598.0", sz: "0.5", time: 10, tid: 1 })).toEqual({
      tid: 1,
      time: 10,
      side: "buy",
      px: 79598,
      sz: 0.5,
      notional: 39799,
    });
    expect(toPrint({ coin: "BTC", side: "A", px: "2", sz: "3", time: 10, tid: 2 })?.side).toBe("sell");
    expect(toPrint({ coin: "BTC", side: "A", px: "0", sz: "3", time: 10, tid: 3 })).toBeNull();
    expect(toPrint({ coin: "BTC", side: "X" as "A", px: "1", sz: "3", time: 10, tid: 4 })).toBeNull();
  });
});

describe("insertPrints", () => {
  it("dedupes by trade id, keeps time order, and prunes old prints", () => {
    let log = insertPrints([], [print(2, 200, "buy", 1), print(1, 100, "sell", 1)], 0);
    expect(log.map((p) => p.tid)).toEqual([1, 2]);
    log = insertPrints(log, [print(2, 200, "buy", 1), print(3, 300, "buy", 1)], 150);
    expect(log.map((p) => p.tid)).toEqual([2, 3]);
  });
});

describe("summarize", () => {
  const log = [print(1, 100, "buy", 30), print(2, 200, "sell", 10), print(3, 300, "buy", 60)];

  it("totals each side within (from, to] and finds the largest print", () => {
    const s = summarize(log, 100, 300);
    expect([s.buyNotional, s.sellNotional, s.buyCount, s.sellCount]).toEqual([60, 10, 1, 1]);
    expect(s.share).toBeCloseTo(85.714, 2);
    expect(s.largest?.tid).toBe(3);
  });

  it("has no share without trades", () => {
    expect(summarize(log, 300, 400).share).toBeUndefined();
  });
});

describe("shareSeries", () => {
  it("samples the trailing-window buy share and skips empty windows", () => {
    const log = [print(1, 1000, "buy", 30), print(2, 2000, "sell", 10), print(3, 9000, "buy", 5)];
    expect(shareSeries(log, 2000, 1000, 0, 6000)).toEqual([
      { time: 1, value: 100 },
      { time: 2, value: 75 },
      { time: 3, value: 0 },
    ]);
  });
});

describe("largeTradeThreshold", () => {
  it("uses the 95th percentile with a floor", () => {
    const log = Array.from({ length: 100 }, (_, i) => print(i, i + 1, "buy", (i + 1) * 1000));
    expect(largeTradeThreshold(log, 0)).toBe(96_000);
    expect(largeTradeThreshold([print(1, 5, "buy", 50)], 0)).toBe(10_000);
    expect(largeTradeThreshold([], 0)).toBe(10_000);
  });
});
