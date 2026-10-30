import { defineConfig, devices } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

// This config drives the smoke test against a *built* SPA served by the real
// FastAPI backend (not `vite dev`) on one port, so we don't need to touch
// vite.config.ts's hardcoded dev-proxy target (`http://localhost:8765`) --
// which on this machine is already occupied by an unrelated service. The
// frontend is rebuilt once in `globalSetup` (web/e2e/global-setup.ts) before
// the backend (which serves web/dist as a static SPA fallback, see
// src/podcast_autopilot/server/app.py) is booted by Playwright's `webServer`.

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "..");
const venvPython = path.join(repoRoot, ".venv", "Scripts", "python.exe");

const PORT = 8788;
const BASE_URL = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.e2e.ts",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 5 * 60 * 1000,
  expect: { timeout: 15 * 1000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: BASE_URL,
    locale: "zh-TW",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: {
    command: `"${venvPython}" -m uvicorn podcast_autopilot.server:create_app --factory --host 127.0.0.1 --port ${PORT}`,
    cwd: repoRoot,
    url: `${BASE_URL}/api/health`,
    reuseExistingServer: false,
    timeout: 120 * 1000,
    env: {
      ...process.env,
      HF_HUB_DISABLE_SYMLINKS: "1",
    },
    stdout: "pipe",
    stderr: "pipe",
  },
});
