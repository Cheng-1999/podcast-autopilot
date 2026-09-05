import { describe, it, expect } from "vitest";
import { resampleForView } from "../src/lib/waveform";

describe("resampleForView", () => {
  it("returns widthPx columns", () => {
    const peaks = Array.from({ length: 100 }, (_, i) => [-i, i]);
    const out = resampleForView(peaks, 100, 0, 100, 40);
    expect(out).toHaveLength(40);
  });

  it("reduces multiple buckets into one column with min/max", () => {
    const peaks = [
      [-10, 10],
      [-50, 5],
      [-5, 80],
      [-1, 1],
    ];
    // duration=4s, 4 buckets => 1s/bucket. View [0,2) covers buckets 0-1.
    const out = resampleForView(peaks, 4, 0, 2, 1);
    expect(out[0]).toEqual([-50, 10]);
  });

  it("handles an empty peaks array without throwing", () => {
    const out = resampleForView([], 0, 0, 1, 10);
    expect(out).toHaveLength(10);
    expect(out.every(([min, max]) => min === 0 && max === 0)).toBe(true);
  });
});
