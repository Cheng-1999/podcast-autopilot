// @vitest-environment node
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect } from "vitest";
import { LocaleContext, interpolate, getMessage } from "../src/i18n";
import { SUPPORTED_LOCALES, type Locale } from "../src/i18n/types";
import type { MessageKey } from "../src/i18n/messages";
import { RunControls } from "../src/components/RunControls";
import { StageGrid } from "../src/components/StageGrid";
import { ItemList } from "../src/components/ItemList";
import { TranscriptPane } from "../src/components/TranscriptPane";
import { LogPanel } from "../src/components/LogPanel";
import { StatusBar } from "../src/components/StatusBar";
import { EpisodesPage } from "../src/pages/EpisodesPage";
import { NewEpisodePage } from "../src/pages/NewEpisodePage";
import type { EpisodeSummary } from "../src/api/types";

// Strings that a prior review round found hard-coded in JSX outside of any
// t() call; a component regressing back to one of these must fail this test.
const FORBIDDEN_LITERALS = [
  "LIVE SSE",
  "(PROFILE)",
  "(MODEL)",
  "(SKIP)",
  "(ITEMS)",
  "(TRANSCRIPT)",
  "(LOG TAIL)",
  "(STAGE GRID)",
  "(PART)",
  "(EPISODES)",
  "(TITLE)",
  "(STATUS)",
  "/ NEW EPISODE",
  "/ CLIPS",
  // Note: "AUTOPILOT" is intentionally kept untranslated as a brand name in
  // every locale's app.brand catalog entry, so it is not a useful literal to
  // forbid here. "DASHBOARD" (app.brand.sub) does vary per locale.
  "DASHBOARD",
];

function makeTranslate(locale: Locale) {
  const missing: string[] = [];
  const t = (key: MessageKey, params?: Record<string, string | number>) => {
    const message = getMessage(locale, key);
    if (!message) missing.push(key);
    return interpolate(message, params);
  };
  return { t, missing };
}

function renderWithLocale(locale: Locale, node: React.ReactElement) {
  const { t, missing } = makeTranslate(locale);
  const value = { locale, setLocale: () => {}, t };
  const html = renderToStaticMarkup(
    React.createElement(
      QueryClientProvider,
      { client: new QueryClient() },
      React.createElement(
        MemoryRouter,
        null,
        React.createElement(LocaleContext.Provider, { value }, node)
      )
    )
  );
  return { html, missing };
}

function assertClean(html: string, missing: string[], locale: Locale) {
  expect(missing).toEqual([]);
  expect(html).not.toMatch(/\{\{\w+\}\}/); // unresolved interpolation placeholder
  // These literals are the pre-i18n English strings; the en catalog can
  // legitimately translate to the same text, so only non-en locales must
  // never surface them (that would mean the copy bypassed t() entirely).
  if (locale !== "en") {
    for (const literal of FORBIDDEN_LITERALS) {
      expect(html).not.toContain(literal);
    }
  }
}

describe("representative component rendering across locales", () => {
  for (const locale of SUPPORTED_LOCALES) {
    it(`renders RunControls in ${locale} without missing keys`, () => {
      const { html, missing } = renderWithLocale(
        locale,
        React.createElement(RunControls, {
          profiles: ["default", "fast"],
          isRunning: false,
          onRun: () => {},
          onCancel: () => {},
        })
      );
      assertClean(html, missing, locale);
      expect(html).toContain(getMessage(locale, "controls.run"));
    });

    it(`renders StageGrid in ${locale} without missing keys`, () => {
      const { html, missing } = renderWithLocale(
        locale,
        React.createElement(StageGrid, {
          parts: [{ stem: "part1" }],
          stagesState: {
            part1: { probe: { status: "ran", elapsed: 1.2 } },
            __assemble__: { assemble: { status: "running" } },
          },
        })
      );
      assertClean(html, missing, locale);
      expect(html).toContain(getMessage(locale, "stage.heading"));
      expect(html).toContain(getMessage(locale, "status.live"));
    });

    it(`renders ItemList in ${locale} without missing keys`, () => {
      const { html, missing } = renderWithLocale(
        locale,
        React.createElement(ItemList, {
          items: [{ id: "1", kind: "keep", start: 0, end: 1.5, reason: "r", enabled: true }],
          selectedItemId: null,
          onSelect: () => {},
          onToggleEnabled: () => {},
          errorsByItemId: new Map(),
        })
      );
      assertClean(html, missing, locale);
      expect(html).toContain(getMessage(locale, "items.heading"));
    });

    it(`renders TranscriptPane in ${locale} without missing keys`, () => {
      const { html, missing } = renderWithLocale(
        locale,
        React.createElement(TranscriptPane, {
          segments: [{ id: 1, start: 0, end: 1, text: "hello" }],
          currentTime: 0,
          onSeek: () => {},
        })
      );
      assertClean(html, missing, locale);
      expect(html).toContain(getMessage(locale, "transcript.heading"));
    });

    it(`renders LogPanel in ${locale} without missing keys`, () => {
      const { html, missing } = renderWithLocale(
        locale,
        React.createElement(LogPanel, {
          logs: ["line one"],
          isOpen: true,
          onToggle: () => {},
          onClose: () => {},
        })
      );
      assertClean(html, missing, locale);
      expect(html).toContain(getMessage(locale, "log.heading"));
    });

    it(`renders StatusBar in ${locale} without missing keys`, () => {
      const { html, missing } = renderWithLocale(
        locale,
        React.createElement(StatusBar, {
          health: {
            ffmpeg: "/usr/bin/ffmpeg",
            ffprobe: "/usr/bin/ffprobe",
            ffmpeg_ok: true,
            whisper_models: { small: true, medium: false },
            free_disk_gb: 42,
          },
          activeJob: null,
        })
      );
      assertClean(html, missing, locale);
      expect(html).toContain(getMessage(locale, "app.brand"));
      expect(html).toContain(getMessage(locale, "app.brand.sub"));
    });

    it(`renders EpisodesPage in ${locale} without missing keys`, () => {
      const queryClient = new QueryClient();
      const episode: EpisodeSummary = {
        id: "ep1",
        path: "ep1",
        example: false,
        title: "Episode one",
        episode: 1,
        parts: ["part1.wav"],
        status: "done",
        last_run_time: 1700000000,
        final_mp3: "ep1/final.mp3",
        duration: 125.4,
        lufs: -16.2,
        job_id: null,
      };
      queryClient.setQueryData(["episodes"], [episode]);
      const { t, missing } = makeTranslate(locale);
      const value = { locale, setLocale: () => {}, t };
      const html = renderToStaticMarkup(
        React.createElement(
          QueryClientProvider,
          { client: queryClient },
          React.createElement(
            MemoryRouter,
            null,
            React.createElement(LocaleContext.Provider, { value }, React.createElement(EpisodesPage))
          )
        )
      );
      assertClean(html, missing, locale);
      expect(html).toContain(getMessage(locale, "episodes.heading"));
    });

    it(`renders NewEpisodePage in ${locale} without missing keys`, () => {
      const queryClient = new QueryClient();
      queryClient.setQueryData(["episodes"], []);
      const { t, missing } = makeTranslate(locale);
      const value = { locale, setLocale: () => {}, t };
      const html = renderToStaticMarkup(
        React.createElement(
          QueryClientProvider,
          { client: queryClient },
          React.createElement(
            MemoryRouter,
            null,
            React.createElement(LocaleContext.Provider, { value }, React.createElement(NewEpisodePage))
          )
        )
      );
      assertClean(html, missing, locale);
      expect(html).toContain(getMessage(locale, "new.heading"));
    });
  }
});

describe("chapter validation error messages across locales", () => {
  for (const locale of SUPPORTED_LOCALES) {
    it(`localizes chapter time and duration errors in ${locale}`, () => {
      const { t, missing } = makeTranslate(locale);
      expect(t("new.chapterTimeError", { time: "bad" })).not.toMatch(/\{\{\w+\}\}/);
      expect(t("new.chapterExceedsDuration", { title: "Intro" })).not.toMatch(/\{\{\w+\}\}/);
      expect(missing).toEqual([]);
    });
  }
});
