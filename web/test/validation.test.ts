import { describe, expect, it } from "vitest";
import { parseTimestamp, reorder, validateChapters } from "../src/api/validation";
describe("chapter validation", () => {
  it("rejects a start past total duration", () => expect(validateChapters([{ start: "01:01", title: "Late" }], 60)).toContain("超過"));
  it("accepts hh:mm:ss", () => { expect(parseTimestamp("01:02:03")).toBe(3723); expect(validateChapters([{ start: "01:02:03", title: "Main" }], 4000)).toBeNull(); });
});
describe("part ordering", () => {
  it("moves a part up or down without mutating the original", () => {
    const parts = ["one", "two", "three"];
    expect(reorder(parts, 1, -1)).toEqual(["two", "one", "three"]);
    expect(reorder(parts, 1, 1)).toEqual(["one", "three", "two"]);
    expect(reorder(parts, 0, -1)).toEqual(parts);
    expect(parts).toEqual(["one", "two", "three"]);
  });
});
