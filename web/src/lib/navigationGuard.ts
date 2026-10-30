/** Registered by whichever page currently holds unsaved edits (e.g. ReviewPage).
 * Global navigation shortcuts (like the "g e" sequence in App.tsx) call
 * confirmNavigation() before leaving so they respect the same dirty-state
 * guard as the page's own back button. */
type GuardFn = () => boolean;

let guard: GuardFn | null = null;

export function registerNavigationGuard(fn: GuardFn | null): void {
  guard = fn;
}

export function confirmNavigation(): boolean {
  return guard ? guard() : true;
}
