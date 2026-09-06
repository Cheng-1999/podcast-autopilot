export const TOUR_STORAGE_KEY = "autopilot.tour.status";

export type TourPersistedStatus = "completed" | "dismissed";

function isTourPersistedStatus(value: unknown): value is TourPersistedStatus {
  return value === "completed" || value === "dismissed";
}

export function getTourStatus(storage: Pick<Storage, "getItem"> = window.localStorage): TourPersistedStatus | null {
  try {
    const raw = storage.getItem(TOUR_STORAGE_KEY);
    return isTourPersistedStatus(raw) ? raw : null;
  } catch {
    // localStorage can throw in private-browsing / disabled-storage modes.
    return null;
  }
}

export function setTourStatus(status: TourPersistedStatus, storage: Pick<Storage, "setItem"> = window.localStorage): void {
  try {
    storage.setItem(TOUR_STORAGE_KEY, status);
  } catch {
    // Persistence is best-effort; ignore quota / disabled-storage errors.
  }
}

/** A "new" user is one who has never finished or dismissed the tour --
 * the only case the tour is allowed to auto-start for. */
export function shouldAutoStart(status: TourPersistedStatus | null): boolean {
  return status === null;
}
