import { describe, it, expect } from "vitest";
import { getStatusDisplay, getStageDisplay } from "../src/api/status";

describe("getStatusDisplay", () => {
  it("maps done correctly", () => {
    const res = getStatusDisplay("done");
    expect(res.label).toBe("已完成");
    expect(res.color).toBe("green");
  });

  it("maps needs-review correctly", () => {
    const res = getStatusDisplay("needs-review");
    expect(res.label).toBe("待審查");
    expect(res.color).toBe("amber");
  });

  it("maps running correctly", () => {
    const res = getStatusDisplay("running");
    expect(res.label).toBe("執行中");
    expect(res.color).toBe("blue");
  });

  it("maps never-run correctly", () => {
    const res = getStatusDisplay("never-run");
    expect(res.label).toBe("未執行");
    expect(res.color).toBe("muted");
  });

  it("maps failed correctly", () => {
    const res = getStatusDisplay("failed");
    expect(res.label).toBe("失敗");
    expect(res.color).toBe("red");
  });

  it("maps invalid correctly", () => {
    const res = getStatusDisplay("invalid");
    expect(res.label).toBe("無效配置");
    expect(res.color).toBe("red");
  });

  it("handles unknown or empty status gracefully", () => {
    const res = getStatusDisplay(null);
    expect(res.label).toBe("未知");
    expect(res.color).toBe("muted");
  });
});

describe("getStageDisplay", () => {
  it("maps running to blue", () => {
    const res = getStageDisplay("running");
    expect(res.label).toBe("running...");
    expect(res.color).toBe("blue");
  });

  it("maps ran with elapsed to green and formatted string", () => {
    const res = getStageDisplay("ran", 2.345);
    expect(res.label).toBe("ran 2.3s");
    expect(res.color).toBe("green");
  });

  it("maps cached to green", () => {
    const res = getStageDisplay("cached");
    expect(res.label).toBe("cached");
    expect(res.color).toBe("green");
  });

  it("maps skipped to muted", () => {
    const res = getStageDisplay("skipped");
    expect(res.label).toBe("skipped");
    expect(res.color).toBe("muted");
  });

  it("maps cancelled to amber", () => {
    const res = getStageDisplay("cancelled");
    expect(res.label).toBe("cancelled");
    expect(res.color).toBe("amber");
  });

  it("maps failed to red", () => {
    const res = getStageDisplay("failed");
    expect(res.label).toBe("failed");
    expect(res.color).toBe("red");
  });
});
