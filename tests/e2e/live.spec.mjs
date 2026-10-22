import { test, expect } from "@playwright/test";

const started = (page, frames = 10) => page.waitForFunction(
  (n) => window.asciiLive && window.asciiLive.stats.frames > n, frames, { timeout: 20000 });

test("camera starts after a click and is drawn live in glyphs", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto("live/");
  await expect(page.locator("#start-panel")).toBeVisible();
  await expect(page).toHaveTitle("E2E live");
  expect(await page.evaluate(() => window.asciiLive.stats.frames)).toBe(0); // nothing before consent
  await page.locator("#start").click();
  await started(page);
  await expect(page.locator("#start-panel")).toBeHidden();
  const lit = await page.evaluate(() => {
    const c = document.getElementById("film");
    const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
    let bright = 0;
    for (let i = 0; i < d.length; i += 4 * 5) if (d[i] > 128) bright++;
    return bright;
  });
  expect(lit).toBeGreaterThan(50);
  expect(errors).toEqual([]);
});

test("density, mirror, freeze and lens controls", async ({ page }) => {
  await page.goto("live/");
  await page.locator("#start").click();
  await started(page);
  const cols = () => page.evaluate(() => window.asciiLive.columns);
  const c0 = await cols();
  await page.keyboard.press("]");
  expect(await cols()).toBeGreaterThan(c0);
  await page.keyboard.press("[");
  await page.keyboard.press("[");
  expect(await cols()).toBeLessThan(c0);
  await started(page, (await page.evaluate(() => window.asciiLive.stats.frames)) + 3); // still running after rebuild

  await page.keyboard.press("m");
  await expect(page.locator("#mirror")).toHaveAttribute("aria-pressed", "false");

  await page.keyboard.press("Space");
  await expect(page.locator("#freeze")).toHaveAttribute("aria-pressed", "true");
  const f1 = await page.evaluate(() => window.asciiLive.stats.frames);
  await page.waitForTimeout(400);
  expect(await page.evaluate(() => window.asciiLive.stats.frames)).toBe(f1);
  await page.keyboard.press("Space");

  const box = await page.locator("#film").boundingBox();
  await page.mouse.move(box.x + box.width * 0.3, box.y + box.height / 2);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 8 });
  await page.waitForFunction(() => window.asciiLive.field.moved.some((m) => m));
});

test("blocked camera permission shows a clear message", async ({ page }) => {
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException("denied", "NotAllowedError"));
  });
  await page.goto("live/");
  await page.locator("#start").click();
  await expect(page.locator("#status")).toContainText("blocked");
  await expect(page.locator("#start")).toBeEnabled();
});

test("no camera API shows a clear message", async ({ page }) => {
  await page.addInitScript(() => { Object.defineProperty(navigator, "mediaDevices", { value: undefined }); });
  await page.goto("live/");
  await expect(page.locator("#status")).toContainText("cannot use a camera");
});
