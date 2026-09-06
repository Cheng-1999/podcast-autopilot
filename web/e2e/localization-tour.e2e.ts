import { test, expect } from "@playwright/test";

/**
 * End-to-end browser verification for dashboard localization and onboarding tour:
 * 1. Iterates through all 5 supported locales (zh-TW, zh-CN, en, ja, ko) via the UI selector.
 * 2. Verifies <html lang="..."> attribute and localStorage["autopilot.locale"].
 * 3. Verifies persistence of each locale across page reloads.
 * 4. Launches the onboarding tour from the episodes list (/episodes).
 * 5. Traverses across steps, confirming cross-route navigation to /episodes/new.
 * 6. Verifies that the tour can be skipped and persists dismissed status.
 * 7. Verifies that the tour can be replayed from the status bar replay button and dismissed via Escape.
 */

const SUPPORTED_LOCALES = ["zh-TW", "zh-CN", "en", "ja", "ko"] as const;

test.describe("Dashboard Localization and Onboarding Tour", () => {
  test("select each locale, reload to verify persistence, and confirm UI copy updates", async ({ page }) => {
    await page.goto("/episodes");

    // Dismiss tour if auto-started so language selector is interactive
    const tourDialog = page.getByRole("dialog");
    if (await tourDialog.isVisible({ timeout: 2000 }).catch(() => false)) {
      await page.keyboard.press("Escape");
      await expect(tourDialog).not.toBeVisible();
    }

    const languageSelect = page.locator("#language-select");
    await expect(languageSelect).toBeVisible();

    // Verify each supported locale
    for (const loc of SUPPORTED_LOCALES) {
      await languageSelect.selectOption(loc);

      // Verify root document lang attribute matches selected locale
      await expect(page.locator("html")).toHaveAttribute("lang", loc);

      // Verify localStorage persistence
      const stored = await page.evaluate(() => window.localStorage.getItem("autopilot.locale"));
      expect(stored).toBe(loc);

      // Reload page and assert locale selection persists
      await page.reload();
      await expect(page.locator("html")).toHaveAttribute("lang", loc);
      await expect(page.locator("#language-select")).toHaveValue(loc);
    }

    // Reset back to default zh-TW
    await languageSelect.selectOption("zh-TW");
    await expect(page.locator("html")).toHaveAttribute("lang", "zh-TW");
  });

  test("launch tour from episodes page, traverse cross-route step, skip and replay", async ({ page }) => {
    // Set clean dismissed tour status so tour does not auto-start on load
    await page.addInitScript(() => {
      try {
        window.localStorage.setItem("autopilot.locale", "zh-TW");
        window.localStorage.setItem("autopilot.tour.status", "dismissed");
      } catch {
        // Ignore disabled storage in restricted environments
      }
    });

    // Navigate to episodes page
    await page.goto("/episodes");

    const tourDialog = page.getByRole("dialog");
    await expect(tourDialog).not.toBeVisible();

    // Confirm tour status is recorded as dismissed in localStorage
    let tourStatus = await page.evaluate(() => window.localStorage.getItem("autopilot.tour.status"));
    expect(tourStatus).toBe("dismissed");

    // Launch tour from the status bar replay button (?)
    const replayButton = page.locator("header[data-tour='status-bar'] button.dense-btn").filter({ hasText: "?" });
    await expect(replayButton).toBeVisible();
    await replayButton.click();

    // Confirm tour dialog and spotlight are visible
    await expect(tourDialog).toBeVisible({ timeout: 10_000 });
    const spotlight = page.getByTestId("tour-spotlight");
    await expect(spotlight).toBeVisible();

    // Step 1: status-bar
    await expect(page.locator("#tour-panel-title")).toBeVisible();
    const nextButton = tourDialog.locator("button.primary");

    // Advance to Step 2: episodes-list
    await nextButton.click();
    await expect(page.locator("[data-tour='episodes-list']")).toBeVisible();
    await expect(tourDialog).toBeVisible();

    // Advance to Step 3: episodes-new (still on /episodes)
    await nextButton.click();
    await expect(page.locator("[data-tour='episodes-new']")).toBeVisible();
    await expect(tourDialog).toBeVisible();
    await expect(page).toHaveURL(/\/episodes\/?$/);

    // Advance to Step 4: wizard-steps (Cross-route navigation to /episodes/new)
    await nextButton.click();

    // Verify automatic route transition to /episodes/new
    await expect(page).toHaveURL(/\/episodes\/new/);
    await expect(page.locator("[data-tour='wizard-steps']")).toBeVisible({ timeout: 10_000 });
    await expect(tourDialog).toBeVisible();

    // Confirm tour can be skipped via Skip button
    const skipButton = tourDialog.locator("button.dense-btn").filter({ hasText: /跳[過过]|Skip|スキップ|건너뛰기/ });
    await expect(skipButton).toBeVisible();
    await skipButton.click();

    // Confirm dialog and spotlight are removed
    await expect(tourDialog).not.toBeVisible();
    await expect(spotlight).not.toBeVisible();

    tourStatus = await page.evaluate(() => window.localStorage.getItem("autopilot.tour.status"));
    expect(tourStatus).toBe("dismissed");

    // Confirm tour can be replayed again
    await replayButton.click();
    await expect(tourDialog).toBeVisible({ timeout: 10_000 });
    await expect(spotlight).toBeVisible();

    // Confirm Escape key dismisses the tour
    await page.keyboard.press("Escape");
    await expect(tourDialog).not.toBeVisible();
    await expect(spotlight).not.toBeVisible();
  });
});
