import React, { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { TOUR_STEPS, type TourStep } from "./steps";
import { extractEpisodeId, getActiveSteps, matchesRoute, resolveStepPath } from "./route";
import { INITIAL_TOUR_STATE, tourReducer } from "./engine";
import { getTourStatus, setTourStatus, shouldAutoStart } from "./storage";

interface TourContextValue {
  step: TourStep | null;
  stepIndex: number;
  totalSteps: number;
  isActive: boolean;
  isRouteReady: boolean;
  next: () => void;
  back: () => void;
  skip: () => void;
  replay: () => void;
}

export const TourContext = createContext<TourContextValue | null>(null);

export const TourProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const location = useLocation();
  const navigate = useNavigate();
  const [state, dispatch] = useReducer(tourReducer, INITIAL_TOUR_STATE);
  const [activeSteps, setActiveSteps] = useState<TourStep[]>([]);
  const hasAutoStartedRef = useRef(false);

  const start = useCallback(() => {
    const episodeId = extractEpisodeId(location.pathname);
    setActiveSteps(getActiveSteps(TOUR_STEPS, episodeId));
    dispatch({ type: "START", episodeId });
  }, [location.pathname]);

  // Auto-start once, only for a user who has never finished or dismissed
  // the tour before (see storage.shouldAutoStart).
  useEffect(() => {
    if (hasAutoStartedRef.current) return;
    hasAutoStartedRef.current = true;
    if (shouldAutoStart(getTourStatus())) {
      start();
    }
    // Intentionally runs once on mount; `start` closes over the initial route.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const next = useCallback(() => {
    if (state.stepIndex + 1 >= activeSteps.length) {
      setTourStatus("completed");
    }
    dispatch({ type: "NEXT", totalSteps: activeSteps.length });
  }, [activeSteps.length, state.stepIndex]);

  const back = useCallback(() => dispatch({ type: "BACK" }), []);

  const skip = useCallback(() => {
    setTourStatus("dismissed");
    dispatch({ type: "SKIP" });
  }, []);

  const replay = useCallback(() => start(), [start]);

  const currentStep = state.status === "active" ? activeSteps[state.stepIndex] ?? null : null;

  // Drive route transitions: when the active step points at a different
  // route than the one we're on, navigate there.
  useEffect(() => {
    if (!currentStep) return;
    const target = resolveStepPath(currentStep.route, location.pathname, state.episodeId);
    if (target && target !== location.pathname) {
      navigate(target);
    }
    // Re-run only when the step itself changes; navigation is one-shot per step.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentStep]);

  const isRouteReady = currentStep ? matchesRoute(currentStep.route, location.pathname) : false;

  const value = useMemo<TourContextValue>(
    () => ({
      step: currentStep,
      stepIndex: state.stepIndex,
      totalSteps: activeSteps.length,
      isActive: state.status === "active",
      isRouteReady,
      next,
      back,
      skip,
      replay,
    }),
    [currentStep, state.stepIndex, activeSteps.length, state.status, isRouteReady, next, back, skip, replay]
  );

  return <TourContext.Provider value={value}>{children}</TourContext.Provider>;
};

export function useTour(): TourContextValue {
  const ctx = useContext(TourContext);
  if (!ctx) {
    throw new Error("useTour must be used within a TourProvider");
  }
  return ctx;
}

/** Same as useTour, but returns null outside a TourProvider instead of
 * throwing -- for chrome (like the replay button) that renders fine either
 * way, including in tests that mount a component without the provider. */
export function useTourOptional(): TourContextValue | null {
  return useContext(TourContext);
}
