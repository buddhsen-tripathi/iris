import { describe, expect, it } from "vitest";
import { placePopover } from "./PointAndAsk";

describe("placePopover", () => {
  const vw = 1500;
  const vh = 950;
  it("opens to the right of a left-side element", () => {
    expect(placePopover({ top: 200, left: 10, width: 240, height: 40 }, { x: 50, y: 210 }, vw, vh)).toEqual({ left: 262, top: 200 });
  });
  it("opens to the left of a right-rail element instead of covering it", () => {
    const rect = { top: 800, left: 1160, width: 330, height: 60 };
    const at = placePopover(rect, { x: 1200, y: 820 }, vw, vh);
    expect(at.left + 380).toBeLessThanOrEqual(rect.left);
    expect(at.top).toBe(vh - 420 - 8);
  });
  it("falls back to the click point for elements too wide for either side", () => {
    expect(placePopover({ top: 300, left: 250, width: 900, height: 300 }, { x: 700, y: 400 }, vw, vh)).toEqual({ left: 714, top: 414 });
  });
});
