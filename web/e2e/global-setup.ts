import { execSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

/** Rebuilds the SPA once before the suite runs, so the backend (started
 * afterwards by Playwright's `webServer`) serves fresh `web/dist` output
 * instead of whatever was last built (see src/podcast_autopilot/server/app.py's
 * static SPA fallback). Runs `npm run build` (tsc -b && vite build) in web/. */
export default function globalSetup(): void {
  const webDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  execSync("npm run build", {
    cwd: webDir,
    stdio: "inherit",
    shell: process.platform === "win32" ? "cmd.exe" : "/bin/sh",
  });
}
