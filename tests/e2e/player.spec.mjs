import { test, expect } from "@playwright/test";

const ready = (page) => page.waitForFunction(() => document.body.classList.contains("ready") && window.asciiFilm);

/** Wait until the frame on screen is the one the clock asks for. */
const settled = (page) => page.waitForFunction(() => {
  const p = window.asciiFilm;
  return p.shown === p.decoder.frameAt(p.time()) && !p.inflight;
});

function watchPage(page) {
  const errors = [];
  const foreign = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("request", (r) => { if (!r.url().startsWith("http://127.0.0.1:8790/")) foreign.push(r.url()); });
  return { errors, foreign };
}

test("loads, draws glyphs, autoplays muted and stays on-origin", async ({ page }) => {
  const w = watchPage(page);
  await page.goto("silent/");
  await ready(page);
  await expect(page).toHaveTitle("E2E silent");
  const info = await page.evaluate(() => {
    const p = window.asciiFilm;
    return { fonts: document.fonts.check('12px "ASCIIFilmFont"'), playing: p.playing, metric: p.renderer.metricError(),
      label: document.getElementById("film").getAttribute("aria-label") };
  });
  expect(info.fonts).toBe(true);
  expect(info.playing).toBe(true);
  expect(info.metric).toBeLessThan(0.02);
  expect(info.label).toBe("Synthetic test film");
  await page.waitForFunction(() => window.asciiFilm.time() > 0.5);
  // Real glyph pixels: the canvas contains both background and foreground colours.
  const lit = await page.evaluate(() => {
    const c = document.getElementById("film");
    const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
    let bright = 0;
    for (let i = 0; i < d.length; i += 4 * 7) if (d[i] > 128) bright++;
    return bright;
  });
  expect(lit).toBeGreaterThan(100);
  expect(w.errors).toEqual([]);
  expect(w.foreign).toEqual([]);
});

test("pause, play and keyboard toggles", async ({ page }) => {
  await page.goto("silent/");
  await ready(page);
  await page.keyboard.press("Space");
  expect(await page.evaluate(() => window.asciiFilm.playing)).toBe(false);
  const t1 = await page.evaluate(() => window.asciiFilm.time());
  await page.waitForTimeout(400);
  expect(await page.evaluate(() => window.asciiFilm.time())).toBeCloseTo(t1, 3);
  await expect(page.locator("#big-play")).toBeVisible();
  await page.keyboard.press("Space");
  await page.waitForFunction((t) => window.asciiFilm.time() > t + 0.2, t1);
  await page.keyboard.press("l");
  await expect(page.locator("#loop")).toHaveAttribute("aria-pressed", "false");
  await page.keyboard.press("t");
  expect(await page.evaluate(() => window.asciiFilm.themeIndex)).toBe(1);
  await expect(page.locator("#mute")).toBeHidden(); // silent film: no audio controls
});

test("seeking selects the right frame at start, middle and end", async ({ page }) => {
  await page.goto("silent/");
  await ready(page);
  await page.evaluate(() => window.asciiFilm.pause());
  const n = await page.evaluate(() => window.asciiFilm.decoder.frameCount);
  for (const [t, expected] of [[0, 0], [2.5, Math.floor(n / 2)], [1e9, n - 1], [1.0, 24]]) {
    await page.evaluate((s) => window.asciiFilm.seek(s), t);
    await settled(page);
    expect(await page.evaluate(() => window.asciiFilm.shown)).toBe(expected);
  }
  await page.keyboard.press("ArrowLeft"); // 1.0 -> 0
  await settled(page);
  expect(await page.evaluate(() => window.asciiFilm.shown)).toBe(0);
  await page.keyboard.press("ArrowRight"); // 0 -> 5 s, clamped to the last frame
  await settled(page);
  expect(await page.evaluate(() => window.asciiFilm.shown)).toBe(n - 1);
  await page.keyboard.press("Shift+ArrowLeft"); // one frame back
  await settled(page);
  expect(await page.evaluate(() => window.asciiFilm.shown)).toBe(n - 2);
});

test("loops seamlessly past the end", async ({ page }) => {
  await page.goto("silent/");
  await ready(page);
  await page.evaluate(() => window.asciiFilm.seek(4.8));
  await page.waitForFunction(() => window.asciiFilm.time() < 1 && window.asciiFilm.playing);
  expect(await page.evaluate(() => window.asciiFilm.ended)).toBe(false);
});

test("stops at the end when loop is off", async ({ page }) => {
  await page.goto("silent/");
  await ready(page);
  await page.keyboard.press("l");
  await page.evaluate(() => window.asciiFilm.seek(4.7));
  await page.waitForFunction(() => window.asciiFilm.ended);
  await settled(page);
  expect(await page.evaluate(() => [window.asciiFilm.playing, window.asciiFilm.shown])).toEqual([false, 119]);
});

test("resizes crisply and keeps the grid aspect", async ({ page }) => {
  await page.goto("silent/");
  await ready(page);
  const measure = () => page.evaluate(() => {
    const p = window.asciiFilm;
    const r = p.renderer;
    return { w: r.canvas.width, h: r.canvas.height, cw: r.cw, ch: r.ch, css: r.canvas.getBoundingClientRect().toJSON(),
      aspect: (p.m.columns * p.m.font.cellWidth) / (p.m.rows * p.m.font.cellHeight) };
  });
  const a = await measure();
  await page.setViewportSize({ width: 600, height: 700 });
  await page.waitForFunction((w) => window.asciiFilm.renderer.canvas.width !== w, a.w);
  const b = await measure();
  for (const m of [a, b]) {
    expect(Number.isInteger(m.cw) && Number.isInteger(m.ch)).toBe(true);
    expect(m.w / m.h).toBeGreaterThan(m.aspect * 0.95);
    expect(m.w / m.h).toBeLessThan(m.aspect * 1.05);
    expect(m.css.width).toBeLessThanOrEqual(1280.5);
  }
  expect(b.css.width).toBeLessThanOrEqual(600.5);
});

test("fullscreen toggles where supported", async ({ page, browserName }) => {
  await page.goto("silent/");
  await ready(page);
  const supported = await page.evaluate(() => Boolean(document.fullscreenEnabled || document.webkitFullscreenEnabled));
  test.skip(!supported, `fullscreen API unavailable in headless ${browserName}`);
  await page.keyboard.press("f");
  const on = await page.waitForFunction(() => Boolean(document.fullscreenElement || document.webkitFullscreenElement), null, { timeout: 3000 }).then(() => true, () => false);
  test.skip(!on, `headless ${browserName} refused fullscreen`);
  await expect(page.locator("#fullscreen")).toHaveAttribute("aria-label", "Exit full screen");
});

test("lens parts the glyphs, ripples spread, and everything returns exactly", async ({ page }) => {
  await page.goto("silent/");
  await ready(page);
  await page.evaluate(() => window.asciiFilm.pause());
  await settled(page);
  const snapshot = () => page.evaluate(() => document.getElementById("film").toDataURL());
  const before = await snapshot();
  const box = await page.locator("#film").boundingBox();
  await page.mouse.move(box.x + box.width * 0.3, box.y + box.height * 0.5);
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5, { steps: 10 });
  await page.waitForTimeout(500);
  const live = await page.evaluate(() => {
    const f = window.asciiFilm.field;
    let moved = 0, maxScale = 1;
    for (let i = 0; i < f.moved.length; i++) { moved += f.moved[i]; maxScale = Math.max(maxScale, f.s[i]); }
    return { moved, maxScale, ripples: f.ripples.length, cursor: getComputedStyle(document.getElementById("film")).cursor };
  });
  expect(live.moved).toBeGreaterThan(30);
  expect(live.maxScale).toBeGreaterThan(1.5);
  expect(live.cursor).toBe("none");
  expect(await snapshot()).not.toBe(before);
  await page.mouse.move(box.x + box.width + 20, box.y + 10);
  await page.waitForFunction(() => !window.asciiFilm.field.active, null, { timeout: 15000 });
  await page.waitForTimeout(50);
  expect(await snapshot()).toBe(before); // every glyph wagged home, pixel for pixel
});

test("I toggles the interaction off and on", async ({ page }) => {
  await page.goto("silent/");
  await ready(page);
  await page.keyboard.press("i");
  const box = await page.locator("#film").boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 5 });
  await page.waitForTimeout(200);
  expect(await page.evaluate(() => window.asciiFilm.field.moved.some((m) => m))).toBe(false);
  await page.keyboard.press("i");
  await page.mouse.move(box.x + box.width / 2 + 40, box.y + box.height / 2, { steps: 5 });
  await page.waitForFunction(() => window.asciiFilm.field.moved.some((m) => m));
});

test("unsupported browser shows a clear message", async ({ page }) => {
  await page.addInitScript(() => { delete window.DecompressionStream; });
  await page.goto("silent/");
  await expect(page.locator("#status")).toContainText("DecompressionStream");
});

test("missing film shows an error", async ({ page }) => {
  await page.route("**/film.ascf", (r) => r.fulfill({ status: 404, body: "nope" }));
  await page.goto("silent/");
  await expect(page.locator("#status")).toContainText("HTTP 404");
});

test("corrupt film shows an error", async ({ page }) => {
  await page.route("**/film.ascf", (r) => r.fulfill({ status: 200, contentType: "application/octet-stream", body: Buffer.alloc(300, 7) }));
  await page.goto("silent/");
  await expect(page.locator("#status")).toContainText("bad magic");
});

test("corrupt manifest shows an error", async ({ page }) => {
  await page.route("**/manifest.json", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ schemaVersion: 1, animation: "https://evil.example/x" }) }));
  await page.goto("silent/");
  await expect(page.locator("#status")).toContainText("manifest.json");
});

test("reduced motion does not autoplay", async ({ browser }) => {
  const ctx = await browser.newContext({ reducedMotion: "reduce" });
  const page = await ctx.newPage();
  await page.goto("silent/");
  await ready(page);
  expect(await page.evaluate(() => window.asciiFilm.playing)).toBe(false);
  expect(await page.evaluate(() => window.asciiFilm.field)).toBeNull(); // no glyph physics either
  await expect(page.locator("#big-play")).toBeVisible();
  await ctx.close();
});
