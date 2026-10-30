import { describe, it, expect } from "vitest";
import { computeSecondsRemoved, computeEnabledFillerCount, computeSnippetRange } from "../src/lib/planMath";
import type { PlanItem } from "../src/api/types";

const fixture: PlanItem[] = [
  { id: "keep-0", kind: "keep", start: 0, end: 5.2, reason: "speech", enabled: true },
  { id: "cut-1", kind: "cut", start: 5.2, end: 7.0, reason: "pause 1.8s -> 0s", enabled: true },
  { id: "keep-1", kind: "keep", start: 7.0, end: 20.0, reason: "speech", enabled: true },
  { id: "filler-2", kind: "filler", start: 12.3, end: 12.8, reason: "filler:那個", enabled: false },
  { id: "filler-3", kind: "filler", start: 15.0, end: 15.6, reason: "filler:嗯", enabled: true },
];

describe("computeSecondsRemoved", () => {
  it("matches audit.py's total_cut_duration: enabled cut+filler items only", () => {
    // 1.8 (cut-1) + 0.6 (filler-3, enabled) -- filler-2 is disabled, keeps never count.
    expect(computeSecondsRemoved(fixture)).toBeCloseTo(1.8 + 0.6, 6);
  });

  it("is zero when nothing removable is enabled", () => {
    const allDisabled = fixture.map((it) => ({ ...it, enabled: it.kind === "keep" }));
    expect(computeSecondsRemoved(allDisabled)).toBe(0);
  });

  it("counts a re-enabled filler once it is toggled on", () => {
    const toggled = fixture.map((it) => (it.id === "filler-2" ? { ...it, enabled: true } : it));
    expect(computeSecondsRemoved(toggled)).toBeCloseTo(1.8 + 0.5 + 0.6, 6);
  });
});

describe("computeEnabledFillerCount", () => {
  it("counts only enabled filler-kind items", () => {
    expect(computeEnabledFillerCount(fixture)).toBe(1);
  });

  it("updates when a filler is toggled", () => {
    const toggled = fixture.map((it) => (it.id === "filler-2" ? { ...it, enabled: true } : it));
    expect(computeEnabledFillerCount(toggled)).toBe(2);
  });
});

describe("computeSnippetRange", () => {
  it("pads 1.5s before start and after end", () => {
    const range = computeSnippetRange({ start: 10, end: 12 }, 100);
    expect(range.start).toBeCloseTo(8.5, 6);
    expect(range.end).toBeCloseTo(13.5, 6);
  });

  it("clamps the start at 0 near the beginning of the part", () => {
    const range = computeSnippetRange({ start: 0.5, end: 1.5 }, 100);
    expect(range.start).toBe(0);
    expect(range.end).toBeCloseTo(3.0, 6);
  });

  it("clamps the end at the part duration near the end of the part", () => {
    const range = computeSnippetRange({ start: 98, end: 99.5 }, 100);
    expect(range.start).toBeCloseTo(96.5, 6);
    expect(range.end).toBe(100);
  });

  it("supports a custom pad amount", () => {
    const range = computeSnippetRange({ start: 10, end: 12 }, 100, 0.5);
    expect(range.start).toBeCloseTo(9.5, 6);
    expect(range.end).toBeCloseTo(12.5, 6);
  });
});
