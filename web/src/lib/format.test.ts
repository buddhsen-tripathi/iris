import { describe, expect, it } from "vitest";
import { age, compact, decimalsFor, pct, price } from "./format";

describe("price formatting", () => {
  it("scales decimals with magnitude", () => {
    expect(decimalsFor(81584.7)).toBe(2);
    expect(decimalsFor(368.78)).toBe(2);
    expect(decimalsFor(75.5)).toBe(3);
    expect(decimalsFor(2.5)).toBe(4);
    expect(decimalsFor(0.5)).toBe(4);
    expect(decimalsFor(0.0895263739)).toBe(5);
    expect(decimalsFor(0.00001234)).toBe(8);
  });

  it("formats prices, percents, and compact values", () => {
    expect(price("81584.7")).toBe("81,584.70");
    expect(price(undefined)).toBe("—");
    expect(price("abc")).toBe("—");
    expect(pct("-2.41")).toBe("−2.41%");
    expect(pct(0.4)).toBe("+0.40%");
    expect(pct("0")).toBe("0.00%");
    expect(compact("1595150350429", "$")).toBe("$1.6T");
  });

  it("formats ages", () => {
    expect(age(0, 4_000)).toBe("4s");
    expect(age(0, 125_000)).toBe("2m");
    expect(age(0, 7_300_000)).toBe("2h");
    expect(age(0, 100_000_000)).toBe("27h");
    expect(age(0, 260_000_000)).toBe("3d");
    expect(age(undefined, 0)).toBe("—");
  });
});
