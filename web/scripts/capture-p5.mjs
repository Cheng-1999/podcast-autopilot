import { chromium } from "playwright";
import path from "node:path";

const base = "http://127.0.0.1:8766";
const output = path.resolve("web", "screenshots");
const browser = await chromium.launch({ headless: true });
for (const width of [375, 768, 1280]) {
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  await page.goto(`${base}/episodes/new`, { waitUntil: "networkidle" });
  await page.screenshot({ path: path.join(output, `new-${width}px.png`), fullPage: true });
  await page.goto(`${base}/episodes/ep3.local/clips`, { waitUntil: "networkidle" });
  await page.screenshot({ path: path.join(output, `clips-${width}px.png`), fullPage: true });
  await page.close();
}
await browser.close();
