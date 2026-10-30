// @vitest-environment jsdom
import React from "react";
import ReactDOM from "react-dom/client";
import { act } from "react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { LocaleContext, getMessage, interpolate } from "../src/i18n";
import type { MessageKey } from "../src/i18n/messages";
import { EpisodesPage } from "../src/pages/EpisodesPage";
import type { EpisodeSummary } from "../src/api/types";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../src/api/client", () => ({
  fetchEpisodes: vi.fn(),
  deleteEpisode: vi.fn(),
}));

import { fetchEpisodes, deleteEpisode } from "../src/api/client";

function t(key: MessageKey, params?: Record<string, string | number>) {
  return interpolate(getMessage("en", key), params);
}

const EPISODES: EpisodeSummary[] = [
  {
    id: "ep1", path: "ep1", example: false, title: "Ep 1", episode: 1,
    parts: ["part1.wav"], status: "done", last_run_time: null, final_mp3: null,
    duration: null, lufs: null, job_id: null,
  },
  {
    id: "episode.example", path: "examples/episode.example.yaml", example: true, title: "Example", episode: 3,
    parts: ["a.wav"], status: "never-run", last_run_time: null, final_mp3: null,
    duration: null, lufs: null, job_id: null,
  },
];

function mountEpisodesPage() {
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
          React.createElement(MemoryRouter, { initialEntries: ["/episodes"] }, React.createElement(EpisodesPage))
        )
      )
    );
  });

  return {
    container,
    unmount: () => act(() => root.unmount()),
    buttonWithText: (text: string) => Array.from(container.querySelectorAll("button")).find((b) => b.textContent === text),
  };
}

async function flush() {
  for (let i = 0; i < 10; i++) {
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  }
}

describe("EpisodesPage delete", () => {
  beforeEach(() => {
    vi.mocked(fetchEpisodes).mockResolvedValue(EPISODES);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("does not show a delete button for the bundled example episode", async () => {
    const view = mountEpisodesPage();
    await flush();
    expect(view.container.querySelectorAll("button.danger, .dense-btn.danger").length).toBe(1);
    view.unmount();
  });

  it("confirms, deletes the episode, and refetches the list", async () => {
    const view = mountEpisodesPage();
    await flush();
    vi.mocked(deleteEpisode).mockResolvedValue({ ok: true });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);

    const deleteButton = view.buttonWithText(t("episodes.delete"));
    expect(deleteButton).toBeTruthy();
    act(() => { deleteButton?.click(); });
    await flush();

    expect(confirm).toHaveBeenCalledWith(t("episodes.deleteConfirm", { title: "Ep 1" }));
    expect(deleteEpisode).toHaveBeenCalledWith("ep1");
    expect(fetchEpisodes).toHaveBeenCalledTimes(2);

    confirm.mockRestore();
    view.unmount();
  });

  it("does not delete when the confirm dialog is dismissed", async () => {
    const view = mountEpisodesPage();
    await flush();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);

    const deleteButton = view.buttonWithText(t("episodes.delete"));
    act(() => { deleteButton?.click(); });
    await flush();

    expect(deleteEpisode).not.toHaveBeenCalled();

    confirm.mockRestore();
    view.unmount();
  });

  it("shows an inline error message when deletion fails", async () => {
    const view = mountEpisodesPage();
    await flush();
    vi.mocked(deleteEpisode).mockRejectedValue(new Error("boom"));
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);

    const deleteButton = view.buttonWithText(t("episodes.delete"));
    act(() => { deleteButton?.click(); });
    await flush();

    expect(view.container.textContent).toContain(t("episodes.deleteError", { message: "boom" }));

    confirm.mockRestore();
    view.unmount();
  });
});
