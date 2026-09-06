// @vitest-environment jsdom
// Regression coverage for the manual-cut feature (T-0021): before this, the
// only way to remove audio was via the automatic pause/filler detectors, so
// an off-topic tangent or a retake mistake they didn't flag had no path to
// removal short of hand-editing plan.json. This exercises the "mark start /
// end cut here" flow end to end against a mocked addManualCut.
import React from "react";
import ReactDOM from "react-dom/client";
import { act } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { LocaleContext, getMessage, interpolate } from "../src/i18n";
import type { MessageKey } from "../src/i18n/messages";
import { ReviewPage } from "../src/pages/ReviewPage";
import type { EpisodeDetail, PlanResponse } from "../src/api/types";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
// jsdom has no layout engine, so scrollIntoView (used by ItemList to keep the
// selected row visible) is simply absent.
if (!window.HTMLElement.prototype.scrollIntoView) {
  window.HTMLElement.prototype.scrollIntoView = () => {};
}

vi.mock("../src/api/client", () => ({
  fetchEpisode: vi.fn(),
  fetchPlan: vi.fn(),
  fetchTranscript: vi.fn(),
  fetchPeaks: vi.fn(),
  putPlan: vi.fn(),
  addManualCut: vi.fn(),
  suggestCutsAI: vi.fn(),
  runEpisode: vi.fn(),
  mediaUrl: vi.fn(() => "http://localhost/media.wav"),
  parseReapplyOptions: vi.fn(() => ({ profile: undefined, model: undefined })),
}));

import { fetchEpisode, fetchPlan, fetchTranscript, fetchPeaks, addManualCut, suggestCutsAI } from "../src/api/client";

function t(key: MessageKey, params?: Record<string, string | number>) {
  return interpolate(getMessage("en", key), params);
}

const EPISODE: EpisodeDetail = {
  id: "ep1", path: "ep1", example: false, title: "Ep 1", episode: 1,
  parts: ["part1.wav"], status: "done", last_run_time: null, final_mp3: null,
  duration: null, lufs: null, job_id: null,
  report_available: false,
  parts_detail: [{ stem: "part1", source: null, loudness_before: null, loudness_after: null, seconds_removed: null, transcript: null, plan: null, stages: [], disabled_filler_proposals: [] }],
  assembly: {}, reapply_command: null,
};

const PLAN: PlanResponse = {
  schema: "v1",
  created: "2026-01-01T00:00:00Z",
  source: { path: "part1.clean.wav", sha256: "abc", duration: 60, sr: 16000, channels: 1 },
  profile: {},
  items: [{ id: "keep-0001", kind: "keep", start: 0, end: 60, reason: "identity", enabled: true }],
};

function mountReviewPage() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = ReactDOM.createRoot(container);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const localeValue = { locale: "en" as const, setLocale: () => {}, t };

  act(() => {
    root.render(
      React.createElement(
        QueryClientProvider,
        { client: queryClient },
        React.createElement(
          LocaleContext.Provider,
          { value: localeValue },
          React.createElement(
            MemoryRouter,
            { initialEntries: ["/episodes/ep1/review"] },
            React.createElement(
              Routes,
              null,
              React.createElement(Route, { path: "/episodes/:id/review", element: React.createElement(ReviewPage) })
            )
          )
        )
      )
    );
  });

  return {
    container,
    unmount: () => act(() => root.unmount()),
    buttonWithText: (text: string) => Array.from(container.querySelectorAll("button")).find((b) => b.textContent === text),
    audio: () => container.querySelector("audio") as HTMLAudioElement,
  };
}

async function flush() {
  for (let i = 0; i < 10; i++) {
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  }
}

describe("ReviewPage manual cut", () => {
  beforeEach(() => {
    vi.mocked(fetchEpisode).mockResolvedValue(EPISODE);
    vi.mocked(fetchPlan).mockResolvedValue(PLAN);
    vi.mocked(fetchTranscript).mockResolvedValue({ language: "en", duration: 60, segments: [] });
    vi.mocked(fetchPeaks).mockResolvedValue({ wav_sha256: "abc", buckets: 0, peaks: [] });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("marks a start, confirms the end, and submits the cut range", async () => {
    vi.mocked(addManualCut).mockResolvedValue({ ok: true, id: "manual-0001", seconds_removed: 5, coverage_ratio: 0.1 });
    const view = mountReviewPage();
    await flush();

    const audio = view.audio();
    Object.defineProperty(audio, "currentTime", { value: 10, configurable: true, writable: true });
    act(() => { audio.dispatchEvent(new Event("timeupdate")); });

    const markButton = view.buttonWithText(t("review.markCutStart"));
    expect(markButton).toBeTruthy();
    act(() => { markButton?.click(); });

    expect(view.container.textContent).toContain(t("review.cuttingFrom", { start: "00:10.0" }));

    Object.defineProperty(audio, "currentTime", { value: 15, configurable: true, writable: true });
    act(() => { audio.dispatchEvent(new Event("timeupdate")); });

    const confirmButton = view.buttonWithText(t("review.confirmCut"));
    act(() => { confirmButton?.click(); });
    await flush();

    expect(addManualCut).toHaveBeenCalledWith("ep1", "part1", { start: 10, end: 15, reason: "manual" });
    // Successful submission resets the pending-cut UI back to the mark button.
    expect(view.buttonWithText(t("review.markCutStart"))).toBeTruthy();
    expect(view.buttonWithText(t("review.confirmCut"))).toBeFalsy();

    view.unmount();
  });

  it("cancels a pending cut without calling the API", async () => {
    const view = mountReviewPage();
    await flush();

    act(() => { view.buttonWithText(t("review.markCutStart"))?.click(); });
    expect(view.buttonWithText(t("review.confirmCut"))).toBeTruthy();

    act(() => { view.buttonWithText(t("common.cancel"))?.click(); });
    await flush();

    expect(addManualCut).not.toHaveBeenCalled();
    expect(view.buttonWithText(t("review.markCutStart"))).toBeTruthy();

    view.unmount();
  });

  it("shows the audit rejection inline and keeps the pending cut editable", async () => {
    vi.mocked(addManualCut).mockResolvedValue({ ok: false, errors: ["item manual-0001 overlaps with keep-0001"] });
    const view = mountReviewPage();
    await flush();

    const audio = view.audio();
    Object.defineProperty(audio, "currentTime", { value: 10, configurable: true, writable: true });
    act(() => { audio.dispatchEvent(new Event("timeupdate")); });
    act(() => { view.buttonWithText(t("review.markCutStart"))?.click(); });

    Object.defineProperty(audio, "currentTime", { value: 15, configurable: true, writable: true });
    act(() => { audio.dispatchEvent(new Event("timeupdate")); });
    act(() => { view.buttonWithText(t("review.confirmCut"))?.click(); });
    await flush();

    expect(view.container.textContent).toContain("overlaps with keep-0001");
    view.unmount();
  });
});

describe("ReviewPage AI suggest", () => {
  beforeEach(() => {
    vi.mocked(fetchEpisode).mockResolvedValue(EPISODE);
    vi.mocked(fetchPlan).mockResolvedValue(PLAN);
    vi.mocked(fetchTranscript).mockResolvedValue({ language: "en", duration: 60, segments: [] });
    vi.mocked(fetchPeaks).mockResolvedValue({ wav_sha256: "abc", buckets: 0, peaks: [] });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("lists suggestions and lets the user accept one via the existing manual-cut endpoint", async () => {
    vi.mocked(suggestCutsAI).mockResolvedValue({
      ok: true,
      suggestions: [
        { start: 5, end: 8, reason: "redundant retake", valid: true, errors: [] },
        { start: 20, end: 22, reason: "off-topic tangent", valid: false, errors: ["item overlaps with keep-0001"] },
      ],
    });
    vi.mocked(addManualCut).mockResolvedValue({ ok: true, id: "manual-0001" });

    const view = mountReviewPage();
    await flush();

    act(() => { view.buttonWithText(t("review.aiSuggest"))?.click(); });
    await flush();

    expect(suggestCutsAI).toHaveBeenCalledWith("ep1", "part1");
    expect(view.container.textContent).toContain("redundant retake");
    expect(view.container.textContent).toContain("off-topic tangent");

    const addButtons = Array.from(view.container.querySelectorAll("button")).filter(
      (b) => b.textContent === t("review.aiSuggestAccept")
    );
    // The invalid (overlapping) suggestion's Add button must be disabled --
    // only a human dismissing or an accept of the valid one should be possible.
    expect(addButtons[1].disabled).toBe(true);

    act(() => { addButtons[0].click(); });
    await flush();

    expect(addManualCut).toHaveBeenCalledWith("ep1", "part1", { start: 5, end: 8, reason: "redundant retake" });
    // The accepted suggestion is removed from the list; the rejected one stays for the user to dismiss.
    expect(view.container.textContent).not.toContain("redundant retake");
    expect(view.container.textContent).toContain("off-topic tangent");

    view.unmount();
  });

  it("dismisses a suggestion locally without calling any API", async () => {
    vi.mocked(suggestCutsAI).mockResolvedValue({
      ok: true,
      suggestions: [{ start: 5, end: 8, reason: "redundant retake", valid: true, errors: [] }],
    });

    const view = mountReviewPage();
    await flush();
    act(() => { view.buttonWithText(t("review.aiSuggest"))?.click(); });
    await flush();

    act(() => { view.buttonWithText(t("review.aiSuggestDismiss"))?.click(); });

    expect(addManualCut).not.toHaveBeenCalled();
    expect(view.container.textContent).not.toContain("redundant retake");

    view.unmount();
  });

  it("shows an inline error when the AI CLI is not configured", async () => {
    vi.mocked(suggestCutsAI).mockRejectedValue(new Error("ai_suggest is not configured for this profile"));

    const view = mountReviewPage();
    await flush();
    act(() => { view.buttonWithText(t("review.aiSuggest"))?.click(); });
    await flush();

    expect(view.container.textContent).toContain("ai_suggest is not configured for this profile");

    view.unmount();
  });
});
