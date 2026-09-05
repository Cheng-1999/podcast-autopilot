// Canonical catalog: the source of truth for MessageKey. Every other locale's
// catalog is a Partial of this shape -- a key missing there falls back to here.
const en = {
  "app.brand": "AUTOPILOT",
  "app.brand.sub": "DASHBOARD",
  "nav.episodes": "Episodes",
  "status.idle": "Idle",
  "status.job": "Job",
  "language.selector.label": "Language",
  "greeting.welcome": "Welcome back, {{name}}",
} as const;

export default en;

export type MessageKey = keyof typeof en;
