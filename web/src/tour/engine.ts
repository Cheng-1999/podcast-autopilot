export type TourStatus = "idle" | "active" | "finished" | "dismissed";

export interface TourState {
  status: TourStatus;
  stepIndex: number;
  episodeId: string | null;
}

export const INITIAL_TOUR_STATE: TourState = { status: "idle", stepIndex: 0, episodeId: null };

export type TourAction =
  | { type: "START"; episodeId: string | null }
  | { type: "NEXT"; totalSteps: number }
  | { type: "BACK" }
  | { type: "SKIP" }
  | { type: "FINISH" }
  | { type: "RESET" };

export function tourReducer(state: TourState, action: TourAction): TourState {
  switch (action.type) {
    case "START":
      return { status: "active", stepIndex: 0, episodeId: action.episodeId };
    case "NEXT": {
      if (state.status !== "active") return state;
      const nextIndex = state.stepIndex + 1;
      if (nextIndex >= action.totalSteps) {
        return { ...state, status: "finished" };
      }
      return { ...state, stepIndex: nextIndex };
    }
    case "BACK": {
      if (state.status !== "active") return state;
      return { ...state, stepIndex: Math.max(0, state.stepIndex - 1) };
    }
    case "SKIP":
      if (state.status !== "active") return state;
      return { ...state, status: "dismissed" };
    case "FINISH":
      if (state.status !== "active") return state;
      return { ...state, status: "finished" };
    case "RESET":
      return INITIAL_TOUR_STATE;
    default:
      return state;
  }
}

/** Tab-order wraparound for the tour panel's focus trap: given the index of
 * the currently focused element among `length` focusable elements, returns
 * the index Tab (direction 1) or Shift+Tab (direction -1) should land on. */
export function nextFocusIndex(current: number, length: number, direction: 1 | -1): number {
  if (length <= 0) return -1;
  return (current + direction + length) % length;
}

export const MAX_ANCHOR_ATTEMPTS = 10;

/** Whether the overlay should give up looking for a step's anchor element
 * and skip to the next step -- the anchor may legitimately not exist yet
 * (e.g. it's behind a page's own local UI state the tour doesn't drive). */
export function hasExceededAnchorAttempts(attempts: number, max: number = MAX_ANCHOR_ATTEMPTS): boolean {
  return attempts >= max;
}
