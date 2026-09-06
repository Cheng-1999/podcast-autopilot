// @vitest-environment jsdom
// Regression test for the intermittent "clip won't play" bug: play() used
// `audio.src === thisClipsUrl` as its only signal that the file was already
// loaded. All clips in a part share one source file, so that string check
// stayed true forever after the first load -- including after a load that
// had errored out, or one still in flight from a rapid second click. The fix
// (readySrcRef) only treats a source as ready once `loadedmetadata` actually
// fired for it, and clears that flag on error or on starting a new load.
import React from "react";
import ReactDOM from "react-dom/client";
import { act } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { LocaleContext, getMessage, interpolate } from "../src/i18n";
import type { MessageKey } from "../src/i18n/messages";
import { ClipsPage } from "../src/pages/ClipsPage";
import type { EpisodeDetail } from "../src/api/types";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../src/api/client", () => ({
  fetchEpisode: vi.fn(),
  fetchClips: vi.fn(),
  generateClips: vi.fn(),
  createJobEventSource: vi.fn(() => () => {}),
}));

import { fetchEpisode, fetchClips } from "../src/api/client";

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

function mountClipsPage() {
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
            { initialEntries: ["/episodes/ep1/clips"] },
            React.createElement(
              Routes,
              null,
              React.createElement(Route, { path: "/episodes/:id/clips", element: React.createElement(ClipsPage) })
            )
          )
        )
      )
    );
  });

  return {
    container,
    unmount: () => act(() => root.unmount()),
    playButtons: () => Array.from(container.querySelectorAll("button")).filter((b) => b.textContent === t("common.play") || b.textContent === t("clips.loadingAudio")),
    errorBox: () => container.querySelector(".inline-error"),
    audio: () => container.querySelector("audio") as HTMLAudioElement,
  };
}

async function flush() {
  // React Query's notifyManager and React 19's scheduler don't always resolve on the
  // microtask queue alone (they can hop through setTimeout/MessageChannel), so a chain of
  // `Promise.resolve()` ticks flushed some runs and not others -- the exact kind of race
  // this file exists to catch. A real setTimeout tick drains the macrotask queue too.
  for (let i = 0; i < 10; i++) {
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  }
}

describe("ClipsPage playback (readySrcRef race fix)", () => {
  const originalPlay = window.HTMLMediaElement.prototype.play;
  const originalLoad = window.HTMLMediaElement.prototype.load;

  beforeEach(() => {
    vi.mocked(fetchEpisode).mockResolvedValue(EPISODE);
    vi.mocked(fetchClips).mockResolvedValue({
      candidates: [
        { id: 1, start: 0, end: 5, text: "first", score: 1 },
        { id: 2, start: 10, end: 15, text: "second", score: 1 },
      ],
    });
    window.HTMLMediaElement.prototype.play = vi.fn(() => Promise.resolve());
    window.HTMLMediaElement.prototype.load = vi.fn(function (this: HTMLMediaElement) {
      Object.defineProperty(this, "readyState", { value: 0, configurable: true });
      Object.defineProperty(this, "error", { value: null, configurable: true });
    });
  });

  afterEach(() => {
    window.HTMLMediaElement.prototype.play = originalPlay;
    window.HTMLMediaElement.prototype.load = originalLoad;
    vi.clearAllMocks();
  });

  it("retries the load (instead of silently misplaying) after a failed first load", async () => {
    const view = mountClipsPage();
    await flush();

    const audio = view.audio();
    Object.defineProperty(audio, "readyState", { value: 0, configurable: true });

    let [first] = view.playButtons();
    act(() => { first.click(); });
    expect(view.playButtons()[0].textContent).toBe(t("clips.loadingAudio"));

    act(() => { audio.dispatchEvent(new Event("error")); });
    expect(view.errorBox()?.textContent).toBe(t("clips.playError"));
    expect(view.playButtons()[0].textContent).toBe(t("common.play"));

    // audio.src is still pointed at the shared part file after the failed
    // load. Before the fix, that string equality alone meant the next click
    // skipped reloading entirely and just called audio.play() on the broken
    // element -- silently doing nothing instead of retrying.
    const loadSpy = vi.mocked(window.HTMLMediaElement.prototype.load);
    [first] = view.playButtons();
    act(() => { first.click(); });
    expect(loadSpy).toHaveBeenCalled();
    expect(view.playButtons()[0].textContent).toBe(t("clips.loadingAudio"));

    Object.defineProperty(audio, "readyState", { value: 1, configurable: true });
    act(() => { audio.dispatchEvent(new Event("loadedmetadata")); });
    expect(view.errorBox()).toBeNull();
    expect(view.playButtons()[0].textContent).toBe(t("common.play"));

    view.unmount();
  });

  it("plays a second clip from the same already-loaded file without reloading", async () => {
    const view = mountClipsPage();
    await flush();

    const audio = view.audio();
    Object.defineProperty(audio, "readyState", { value: 0, configurable: true });

    const [firstBtn, secondBtn] = view.playButtons();
    act(() => { firstBtn.click(); });
    Object.defineProperty(audio, "readyState", { value: 1, configurable: true });
    act(() => { audio.dispatchEvent(new Event("loadedmetadata")); });
    expect(view.playButtons()[0].textContent).toBe(t("common.play"));

    const loadSpy = vi.mocked(window.HTMLMediaElement.prototype.load);
    loadSpy.mockClear();
    act(() => { secondBtn.click(); });

    expect(loadSpy).not.toHaveBeenCalled();
    expect(view.playButtons()[1].textContent).toBe(t("common.play"));
    expect(audio.currentTime).toBe(10);

    view.unmount();
  });
});
