// @vitest-environment jsdom
import React from "react";
import ReactDOM from "react-dom/client";
import { act } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { LocaleContext, getMessage, interpolate } from "../src/i18n";
import type { MessageKey } from "../src/i18n/messages";
import { TourProvider } from "../src/tour/context";
import { TourOverlay } from "../src/tour/TourOverlay";
import { StatusBar } from "../src/components/StatusBar";
import { NewEpisodePage } from "../src/pages/NewEpisodePage";
import { tourReducer, INITIAL_TOUR_STATE, nextFocusIndex, hasExceededAnchorAttempts, MAX_ANCHOR_ATTEMPTS } from "../src/tour/engine";
import { extractEpisodeId, matchesRoute, resolveStepPath, getActiveSteps, isStepReachable } from "../src/tour/route";
import { TOUR_STEPS, type TourStep } from "../src/tour/steps";
import { TOUR_STORAGE_KEY, getTourStatus, setTourStatus, shouldAutoStart } from "../src/tour/storage";
import { computeSpotlightRect, computePanelPosition } from "../src/tour/geometry";

// react-dom/client's act() otherwise warns that "the current testing
// environment is not configured to support act(...)" -- it only checks this
// global, it doesn't require React Testing Library.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("tour engine (pure state machine)", () => {
  it("START always resets to step 0 as active", () => {
    const state = tourReducer(INITIAL_TOUR_STATE, { type: "START", episodeId: "ep1" });
    expect(state).toEqual({ status: "active", stepIndex: 0, episodeId: "ep1" });
  });

  it("NEXT advances the step index while steps remain", () => {
    const active = { status: "active" as const, stepIndex: 0, episodeId: null };
    const state = tourReducer(active, { type: "NEXT", totalSteps: 3 });
    expect(state.stepIndex).toBe(1);
    expect(state.status).toBe("active");
  });

  it("NEXT past the last step finishes the tour", () => {
    const active = { status: "active" as const, stepIndex: 2, episodeId: null };
    const state = tourReducer(active, { type: "NEXT", totalSteps: 3 });
    expect(state.status).toBe("finished");
  });

  it("BACK does not go below step 0", () => {
    const active = { status: "active" as const, stepIndex: 0, episodeId: null };
    expect(tourReducer(active, { type: "BACK" }).stepIndex).toBe(0);
  });

  it("SKIP and FINISH only apply while active", () => {
    const idle = INITIAL_TOUR_STATE;
    expect(tourReducer(idle, { type: "SKIP" })).toBe(idle);
    const active = { status: "active" as const, stepIndex: 1, episodeId: null };
    expect(tourReducer(active, { type: "SKIP" }).status).toBe("dismissed");
    expect(tourReducer(active, { type: "FINISH" }).status).toBe("finished");
  });

  it("RESET returns to the initial state", () => {
    const active = { status: "active" as const, stepIndex: 3, episodeId: "ep1" };
    expect(tourReducer(active, { type: "RESET" })).toEqual(INITIAL_TOUR_STATE);
  });

  it("nextFocusIndex wraps forward and backward through a focus trap", () => {
    expect(nextFocusIndex(0, 3, 1)).toBe(1);
    expect(nextFocusIndex(2, 3, 1)).toBe(0);
    expect(nextFocusIndex(0, 3, -1)).toBe(2);
    expect(nextFocusIndex(0, 0, 1)).toBe(-1);
  });

  it("hasExceededAnchorAttempts trips at the configured threshold", () => {
    expect(hasExceededAnchorAttempts(MAX_ANCHOR_ATTEMPTS - 1)).toBe(false);
    expect(hasExceededAnchorAttempts(MAX_ANCHOR_ATTEMPTS)).toBe(true);
  });
});

describe("tour route resolution", () => {
  it("extracts an episode id from a detail route but not from /episodes/new", () => {
    expect(extractEpisodeId("/episodes/ep3.local/review")).toBe("ep3.local");
    expect(extractEpisodeId("/episodes/new")).toBeNull();
    expect(extractEpisodeId("/episodes")).toBeNull();
  });

  it("matchesRoute handles all three route kinds", () => {
    expect(matchesRoute({ kind: "any" }, "/anything")).toBe(true);
    expect(matchesRoute({ kind: "static", path: "/episodes" }, "/episodes")).toBe(true);
    expect(matchesRoute({ kind: "static", path: "/episodes" }, "/episodes/new")).toBe(false);
    expect(matchesRoute({ kind: "episode", suffix: "/review" }, "/episodes/ep1/review")).toBe(true);
    expect(matchesRoute({ kind: "episode", suffix: "/review" }, "/episodes/ep1")).toBe(false);
    expect(matchesRoute({ kind: "episode", suffix: "" }, "/episodes")).toBe(false);
  });

  it("resolveStepPath cannot resolve an episode-scoped route without a known episode id", () => {
    expect(resolveStepPath({ kind: "episode", suffix: "/clips" }, "/episodes", null)).toBeNull();
    expect(resolveStepPath({ kind: "episode", suffix: "/clips" }, "/episodes", "ep1")).toBe("/episodes/ep1/clips");
    expect(resolveStepPath({ kind: "static", path: "/episodes/new" }, "/episodes", null)).toBe("/episodes/new");
    expect(resolveStepPath({ kind: "any" }, "/episodes/ep1", null)).toBe("/episodes/ep1");
  });

  it("filters episode-scoped steps out of the active list when no episode is known", () => {
    expect(isStepReachable({ kind: "episode", suffix: "" }, null)).toBe(false);
    expect(isStepReachable({ kind: "episode", suffix: "" }, "ep1")).toBe(true);
    const active = getActiveSteps(TOUR_STEPS, null);
    expect(active.every((s) => s.route.kind !== "episode")).toBe(true);
    expect(active.length).toBeLessThan(TOUR_STEPS.length);
    const withEpisode = getActiveSteps(TOUR_STEPS, "ep1");
    expect(withEpisode.length).toBe(TOUR_STEPS.length);
  });
});

describe("tour persistence", () => {
  function fakeStorage(initial: Record<string, string> = {}) {
    const data: Record<string, string> = { ...initial };
    return {
      getItem: (key: string) => (key in data ? data[key] : null),
      setItem: (key: string, value: string) => {
        data[key] = value;
      },
    };
  }

  it("round-trips a valid status and rejects garbage", () => {
    const storage = fakeStorage();
    setTourStatus("completed", storage);
    expect(getTourStatus(storage)).toBe("completed");
    const corrupted = fakeStorage({ [TOUR_STORAGE_KEY]: "not-a-status" });
    expect(getTourStatus(corrupted)).toBeNull();
  });

  it("only auto-starts for a user with no recorded status", () => {
    expect(shouldAutoStart(null)).toBe(true);
    expect(shouldAutoStart("completed")).toBe(false);
    expect(shouldAutoStart("dismissed")).toBe(false);
  });

  it("getItem/setItem failures (private browsing) degrade to a no-op instead of throwing", () => {
    const throwing = {
      getItem: () => {
        throw new Error("disabled");
      },
      setItem: () => {
        throw new Error("disabled");
      },
    };
    expect(() => setTourStatus("dismissed", throwing)).not.toThrow();
    expect(getTourStatus(throwing)).toBeNull();
  });
});

describe("tour geometry", () => {
  it("pads the spotlight around the anchor", () => {
    const rect = computeSpotlightRect({ top: 100, left: 50, width: 20, height: 10 }, 8);
    expect(rect).toEqual({ top: 92, left: 42, width: 36, height: 26 });
  });

  it("falls back to a side that fits and clamps to the viewport", () => {
    // Anchor pinned to the very top: "top" placement has no room, so it
    // should fall back to "bottom" instead of rendering off-screen.
    const pos = computePanelPosition(
      { top: 0, left: 500, width: 40, height: 20 },
      "top",
      { width: 300, height: 150 },
      { width: 1000, height: 800 }
    );
    expect(pos.placement).toBe("bottom");
    expect(pos.top).toBeGreaterThanOrEqual(0);

    // Anchor pinned to the right edge: panel must not overflow the viewport.
    const clamped = computePanelPosition(
      { top: 100, left: 980, width: 20, height: 20 },
      "right",
      { width: 300, height: 150 },
      { width: 1000, height: 800 }
    );
    expect(clamped.left + 300).toBeLessThanOrEqual(1000);
  });
});

// ---------------------------------------------------------------------------
// Integration: TourProvider + TourOverlay mounted into a real jsdom document.
// These exercise the wiring the pure unit tests above can't reach: DOM
// anchor discovery, route navigation, keyboard dismissal, and focus.
// ---------------------------------------------------------------------------

function t(key: MessageKey, params?: Record<string, string | number>) {
  return interpolate(getMessage("en", key), params);
}

function LocationProbe() {
  const location = useLocation();
  return React.createElement("div", { "data-testid": "location" }, location.pathname);
}

function mountTour(anchors: string[], initialPath = "/episodes") {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = ReactDOM.createRoot(container);
  const localeValue = { locale: "en" as const, setLocale: () => {}, t };

  act(() => {
    root.render(
      React.createElement(
        MemoryRouter,
        { initialEntries: [initialPath] },
        React.createElement(
          LocaleContext.Provider,
          { value: localeValue },
          React.createElement(
            TourProvider,
            null,
            React.createElement(
              React.Fragment,
              null,
              React.createElement(LocationProbe),
              ...anchors.map((a) => React.createElement("div", { key: a, "data-tour": a }, a)),
              React.createElement(TourOverlay)
            )
          )
        )
      )
    );
  });

  return {
    container,
    unmount: () => act(() => root.unmount()),
    location: () => container.querySelector('[data-testid="location"]')?.textContent ?? "",
    dialog: () => container.querySelector('[role="dialog"]'),
    buttons: () => Array.from(container.querySelectorAll("button")),
  };
}

function mountTourWithChrome(initialPath = "/episodes") {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = ReactDOM.createRoot(container);
  const localeValue = { locale: "en" as const, setLocale: () => {}, t };

  act(() => {
    root.render(
      React.createElement(
        MemoryRouter,
        { initialEntries: [initialPath] },
        React.createElement(
          LocaleContext.Provider,
          { value: localeValue },
          React.createElement(
            TourProvider,
            null,
            React.createElement(
              React.Fragment,
              null,
              React.createElement(StatusBar, { health: null, activeJob: null }),
              React.createElement(TourOverlay)
            )
          )
        )
      )
    );
  });

  return {
    unmount: () => act(() => root.unmount()),
    dialog: () => container.querySelector('[role="dialog"]'),
    buttons: () => Array.from(container.querySelectorAll("button")),
    replayButton: () => container.querySelector<HTMLButtonElement>(`[aria-label="${t("tour.replay")}"]`),
  };
}

const FIRST_FIVE_STEPS: TourStep[] = TOUR_STEPS.slice(0, 5); // status-bar, episodes-list, episodes-new, wizard-steps, wizard-upload -- the only steps reachable with no episode in context

describe("TourOverlay integration", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    document.body.innerHTML = "";
    vi.useRealTimers();
  });

  it("auto-starts for a new user and spotlights the first step", () => {
    const harness = mountTour(["status-bar", "episodes-list", "episodes-new", "wizard-steps"]);
    const dialog = harness.dialog();
    expect(dialog).not.toBeNull();
    expect(dialog?.textContent).toContain(t("tour.step.statusBar.title"));
    expect(dialog?.textContent).toContain("1 / 5");
    harness.unmount();
  });

  it("does not auto-start for a user who already dismissed the tour", () => {
    window.localStorage.setItem(TOUR_STORAGE_KEY, "dismissed");
    const harness = mountTour(["status-bar"]);
    expect(harness.dialog()).toBeNull();
    harness.unmount();
  });

  it("advances on Next and navigates the route for a static-route step", () => {
    const harness = mountTour(FIRST_FIVE_STEPS.map((s) => s.anchor));
    const clickNext = () => {
      const next = harness.buttons().find((b) => b.textContent === t("tour.next") || b.textContent === t("tour.finish"));
      act(() => next?.click());
    };

    clickNext(); // -> episodes-list
    clickNext(); // -> episodes-new
    expect(harness.location()).toBe("/episodes");
    clickNext(); // -> wizard-steps, a static route under /episodes/new
    expect(harness.location()).toBe("/episodes/new");
    expect(harness.dialog()?.textContent).toContain(t("tour.step.wizardSteps.title"));
    harness.unmount();
  });

  it("Back retreats a step without leaving the active state", () => {
    const harness = mountTour(FIRST_FIVE_STEPS.map((s) => s.anchor));
    const click = (label: string) => {
      const btn = harness.buttons().find((b) => b.textContent?.startsWith(label));
      act(() => btn?.click());
    };
    click(t("tour.next"));
    expect(harness.dialog()?.textContent).toContain("2 / 5");
    click(t("tour.back"));
    expect(harness.dialog()?.textContent).toContain("1 / 5");
    harness.unmount();
  });

  it("Escape dismisses the tour and persists the dismissal", () => {
    const harness = mountTour(["status-bar"]);
    expect(harness.dialog()).not.toBeNull();
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(harness.dialog()).toBeNull();
    expect(window.localStorage.getItem(TOUR_STORAGE_KEY)).toBe("dismissed");
    harness.unmount();
  });

  it("finishing the last step persists completion", () => {
    const harness = mountTour(["status-bar"]); // only anchor present; every later step's anchor is missing
    const clickNext = () => {
      const btn = harness.buttons().find((b) => b.textContent === t("tour.next") || b.textContent === t("tour.finish"));
      act(() => btn?.click());
    };
    for (let i = 0; i < FIRST_FIVE_STEPS.length; i++) clickNext();
    expect(window.localStorage.getItem(TOUR_STORAGE_KEY)).toBe("completed");
    expect(harness.dialog()).toBeNull();
    harness.unmount();
  });

  it("skips a step whose anchor never appears instead of hanging", () => {
    vi.useFakeTimers();
    // "episodes-list" is deliberately missing so the overlay must give up on
    // it and move itself to "episodes-new".
    const harness = mountTour(["status-bar", "episodes-new"]);
    act(() => {
      const next = harness.buttons().find((b) => b.textContent === t("tour.next"));
      next?.click();
    });
    expect(harness.dialog()?.textContent).toContain(t("tour.step.episodesList.title"));
    act(() => {
      vi.advanceTimersByTime((MAX_ANCHOR_ATTEMPTS + 2) * 80);
    });
    expect(harness.dialog()?.textContent).toContain(t("tour.step.episodesNew.title"));
    harness.unmount();
  });

  it("moves focus onto the panel for each step and traps Tab inside it", () => {
    const harness = mountTour(["status-bar", "episodes-list"]);
    const dialog = harness.dialog();
    expect(document.activeElement).toBe(dialog);

    const buttons = harness.buttons();
    const last = buttons[buttons.length - 1];
    act(() => last.focus());
    expect(document.activeElement).toBe(last);

    act(() => {
      last.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true }));
    });
    expect(document.activeElement).toBe(buttons[0]);
    harness.unmount();
  });

  it("Shift+Tab from the initially focused dialog wraps to the last button", () => {
    const harness = mountTour(["status-bar", "episodes-list"]);
    const dialog = harness.dialog();
    expect(document.activeElement).toBe(dialog);

    const buttons = harness.buttons();
    act(() => {
      dialog?.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true, cancelable: true })
      );
    });
    expect(document.activeElement).toBe(buttons[buttons.length - 1]);
    harness.unmount();
  });

  it("replay from the global chrome (StatusBar) restarts a finished tour", () => {
    const harness = mountTourWithChrome();
    const clickNext = () => {
      const btn = harness.buttons().find((b) => b.textContent === t("tour.next") || b.textContent === t("tour.finish"));
      act(() => btn?.click());
    };
    for (let i = 0; i < FIRST_FIVE_STEPS.length; i++) clickNext();
    expect(harness.dialog()).toBeNull(); // finished after the last of the 5 reachable steps

    const replay = harness.replayButton();
    expect(replay).not.toBeNull();
    act(() => replay?.click());

    expect(harness.dialog()).not.toBeNull();
    expect(harness.dialog()?.textContent).toContain("1 / 5");
    harness.unmount();
  });

  // Regression: the "wizard-upload" step targets NewEpisodePage's step 2,
  // but the page only renders that section when its own local `step` state
  // is 2. The synthetic-anchor harnesses above can't catch this because they
  // fake the anchor directly instead of rendering the real page -- this test
  // mounts NewEpisodePage itself so the tour has to actually reach the anchor.
  it("reaching the wizard-upload step lands on NewEpisodePage's upload section", () => {
    vi.useFakeTimers();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = ReactDOM.createRoot(container);
    const localeValue = { locale: "en" as const, setLocale: () => {}, t };
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    act(() => {
      root.render(
        React.createElement(
          MemoryRouter,
          { initialEntries: ["/episodes/new"] },
          React.createElement(
            QueryClientProvider,
            { client: queryClient },
            React.createElement(
              LocaleContext.Provider,
              { value: localeValue },
              React.createElement(
                TourProvider,
                null,
                React.createElement(
                  React.Fragment,
                  null,
                  React.createElement(NewEpisodePage),
                  React.createElement(TourOverlay)
                )
              )
            )
          )
        )
      );
    });

    const dialog = () => container.querySelector('[role="dialog"]');
    const clickNext = () => {
      const next = Array.from(container.querySelectorAll("button")).find(
        (b) => b.textContent === t("tour.next") || b.textContent === t("tour.finish")
      );
      act(() => next?.click());
    };

    // status-bar/episodes-list/episodes-new have no anchor in this harness
    // (only NewEpisodePage is mounted) and each gets skipped by the polling
    // fallback in turn -- three separate skip cycles (each needs its own
    // act() flush for the route-change effect to land) to reach wizard-steps,
    // the first step whose anchor actually exists.
    for (let i = 0; i < 3; i++) {
      act(() => {
        vi.advanceTimersByTime((MAX_ANCHOR_ATTEMPTS + 2) * 80);
      });
    }
    expect(dialog()?.textContent).toContain(t("tour.step.wizardSteps.title"));

    clickNext();
    expect(dialog()?.textContent).toContain(t("tour.step.wizardUpload.title"));
    expect(container.querySelector('[data-tour="wizard-upload"]')).not.toBeNull();

    act(() => root.unmount());
  });
});
