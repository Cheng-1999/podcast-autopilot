import { describe, it, expect, vi, afterEach } from "vitest";
import { putPlan } from "../src/api/client";

describe("putPlan", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("resolves with the structured audit errors on a 422 response instead of throwing", async () => {
    const body = { ok: false, errors: ["item cut-0001 and cut-0002 overlap: [1, 2) vs [1.5, 3)"] };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 422,
        ok: false,
        json: () => Promise.resolve(body),
      })
    );

    const result = await putPlan("ep3.local", "EP3-1", [{ id: "cut-0001", enabled: true }]);

    expect(result).toEqual(body);
  });

  it("throws on a non-422 failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 500,
        ok: false,
        text: () => Promise.resolve("boom"),
      })
    );

    await expect(putPlan("ep3.local", "EP3-1", [])).rejects.toThrow("boom");
  });

  it("resolves with the success payload on 200", async () => {
    const body = { ok: true, seconds_removed: 8, coverage_ratio: 0.97 };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 200,
        ok: true,
        json: () => Promise.resolve(body),
      })
    );

    const result = await putPlan("ep3.local", "EP3-1", []);
    expect(result).toEqual(body);
  });
});
