import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

/** Smoke test for the bundled synthetic example episode
 * (examples/episode.example.yaml, discovered by the backend under id
 * "episode.example" -- see src/podcast_autopilot/server/episodes.py's
 * discover_manifests). Drives the real UI: open the episode, start a run,
 * wait for it to finish, open the review screen, flip one plan item's
 * `enabled` flag and save, then confirms plan.json actually changed on disk
 * (the only thing that proves the save round-tripped through the backend). */

const EPISODE_ID = "episode.example";
const PART_ID = "example-part-1";
const PLAN_ITEM_ID = "keep-0001";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const planPath = path.join(repoRoot, "out", EPISODE_ID, "parts", PART_ID, "plan.json");

function readPlanItemEnabled(): boolean {
  const plan = JSON.parse(fs.readFileSync(planPath, "utf-8"));
  const item = plan.items.find((it: { id: string }) => it.id === PLAN_ITEM_ID);
  if (!item) throw new Error(`plan item ${PLAN_ITEM_ID} not found in ${planPath}`);
  return item.enabled;
}

test("run the bundled example episode and save a plan edit through the real UI", async ({ page }) => {
  // Dismiss onboarding tour if it auto-starts so smoke test can interact with episode table
  await page.addInitScript(() => {
    try {
      window.localStorage.setItem("autopilot.locale", "zh-TW");
      window.localStorage.setItem("autopilot.tour.status", "dismissed");
    } catch {
      // Ignore disabled localStorage in restricted browser modes
    }
  });

  // 1+2. Episodes list -> find the bundled example.
  await page.goto("/episodes");
  const row = page.getByTestId(`episode-row-${EPISODE_ID}`);
  await expect(row).toBeVisible({ timeout: 30_000 });
  await expect(row).toContainText(/EXAMPLE|範例/);
  await row.click();

  await expect(page).toHaveURL(new RegExp(`/episodes/${EPISODE_ID.replace(".", "\\.")}$`));

  // 3. Start a run. Pick model "small" so it matches the model already used
  // to populate out/episode.example (see stage_cache.json), so every stage
  // hits cache and the run finishes in seconds instead of re-transcribing.
  await page.locator("#model-select").selectOption("small");
  await page.getByTestId("run-button").click();

  // 4. Poll the UI (not the raw API) until the run reaches a terminal,
  // successful status. Generous timeout: a fully-cached rerun of this 40s
  // synthetic episode should take well under a minute, but CPU whisper /
  // ffmpeg calls on a shared machine can be slow, so allow a few minutes.
  const status = page.getByTestId("episode-status");
  await expect(status).toHaveText(/已完成|Done|完了|완료/, { timeout: 4 * 60 * 1000 });

  // 5. Open the review screen for a part of that episode.
  const beforeEnabled = readPlanItemEnabled();
  await page.locator("a[href$='/review']").click();
  await expect(page).toHaveURL(new RegExp(`/episodes/${EPISODE_ID.replace(".", "\\.")}/review$`));

  const toggle = page.getByTestId(`item-toggle-${PLAN_ITEM_ID}`);
  await expect(toggle).toBeVisible({ timeout: 30_000 });
  await expect(toggle).toBeChecked({ checked: beforeEnabled });

  // 6. Toggle one plan item's enabled state in the UI and save.
  const saveButton = page.getByTestId("save-plan-button");
  await expect(saveButton).toBeDisabled(); // nothing dirty yet
  await toggle.click();
  await expect(toggle).toBeChecked({ checked: !beforeEnabled });
  await expect(saveButton).toBeEnabled();

  const putResponse = page.waitForResponse(
    (resp) =>
      resp.url().includes(`/api/episodes/${EPISODE_ID}/parts/${PART_ID}/plan`) &&
      resp.request().method() === "PUT"
  );
  await saveButton.click();
  const resp = await putResponse;
  expect(resp.status(), "PUT .../plan should succeed (audit_plan must accept the toggle)").toBe(200);
  await expect(page.getByText(/已儲存|已保存|Saved|保存済み|저장됨/)).toBeVisible({ timeout: 15_000 });

  // 7. The actual assertion of success: plan.json changed on disk, and the
  // toggled item's `enabled` field flipped exactly as expected.
  const afterEnabled = readPlanItemEnabled();
  expect(afterEnabled).toBe(!beforeEnabled);
});
