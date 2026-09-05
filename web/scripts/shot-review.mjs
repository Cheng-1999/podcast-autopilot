import { chromium } from "playwright";
import path from "node:path";

const BASE = "http://localhost:8766";
const EP = "ep3.local";
const OUT = path.resolve("screenshots");

async function main() {
  const browser = await chromium.launch();
  for (const width of [1280, 768]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    const consoleErrors = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });
    page.on("pageerror", (err) => consoleErrors.push(String(err)));

    await page.goto(`${BASE}/episodes/${EP}/review`, { waitUntil: "networkidle" });
    await page.waitForSelector("canvas", { timeout: 15000 });
    await page.waitForTimeout(800);
    await page.screenshot({ path: path.join(OUT, `review-${width}px.png`), fullPage: true });

    // interact: select first filler item (filler-0001) and toggle it, play a snippet
    const fillerRow = page.locator("tr:has-text('filler-0001')").first();
    if (await fillerRow.count()) {
      await fillerRow.click();
      await page.waitForTimeout(300);
    }
    await page.screenshot({ path: path.join(OUT, `review-selected-${width}px.png`), fullPage: true });

    if (consoleErrors.length) {
      console.log(`[width=${width}] console errors:`, consoleErrors);
    } else {
      console.log(`[width=${width}] no console errors`);
    }

    await page.goto(`${BASE}/episodes/${EP}/deliverables`, { waitUntil: "networkidle" });
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(OUT, `deliverables-${width}px.png`), fullPage: true });

    await page.close();
  }
  await browser.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
