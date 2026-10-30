import type { TourRoute } from "./steps";

/** Extracts the episode id from a pathname like "/episodes/ep1/review",
 * or null when there is none (including "/episodes/new", which is a
 * literal route segment rather than an id). */
export function extractEpisodeId(pathname: string): string | null {
  const match = pathname.match(/^\/episodes\/([^/]+)/);
  if (!match) return null;
  if (match[1] === "new") return null;
  return decodeURIComponent(match[1]);
}

export function matchesRoute(route: TourRoute, pathname: string): boolean {
  if (route.kind === "any") return true;
  if (route.kind === "static") return pathname === route.path;
  const id = extractEpisodeId(pathname);
  if (!id) return false;
  return pathname === `/episodes/${id}${route.suffix}`;
}

/** The path to navigate to for a step, or null when it needs an episode id
 * that isn't known yet (the step is currently unreachable). */
export function resolveStepPath(route: TourRoute, currentPathname: string, episodeId: string | null): string | null {
  if (route.kind === "any") return currentPathname;
  if (route.kind === "static") return route.path;
  if (!episodeId) return null;
  return `/episodes/${episodeId}${route.suffix}`;
}

export function isStepReachable(route: TourRoute, episodeId: string | null): boolean {
  return route.kind !== "episode" || episodeId !== null;
}

/** Filters a step list down to the ones reachable given the episode id known
 * when the tour started -- episode-scoped steps drop out entirely when the
 * tour is launched with no episode in context, instead of forcing navigation
 * into an episode the user never opened. */
export function getActiveSteps<T extends { route: TourRoute }>(steps: T[], episodeId: string | null): T[] {
  return steps.filter((step) => isStepReachable(step.route, episodeId));
}
