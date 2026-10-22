// Measure playback of a publish directory in headless Chromium and WebKit.
//   node scripts/profile-player.mjs [dir] [seconds]
// Starts scripts/serve.py, plays the film and reports frames shown vs expected,
// skipped frames, per-frame draw cost and decode cost.
import { chromium, webkit } from "@playwright/test";
import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";

const dir = process.argv[2] || "www";
const seconds = Number(process.argv[3] || 8);
const port = 8791;
const server = spawn(process.env.PYTHON || "python3", ["scripts/serve.py", dir, String(port)], { stdio: "ignore" });
await sleep(800);

try {
  for (const [name, type] of [["chromium", chromium], ["webkit", webkit]]) {
    const browser = await type.launch();
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 2 });
    await page.goto(`http://127.0.0.1:${port}/`);
    await page.waitForFunction(() => document.body.classList.contains("ready") && window.asciiFilm, null, { timeout: 30000 });
    const result = await page.evaluate(async (secs) => {
      const p = window.asciiFilm;
      const r = p.renderer;
      const d = p.decoder;
      let drawMs = 0, draws = 0, decodeMs = 0, decodes = 0;
      const draw = r.draw.bind(r);
      r.draw = (g) => { const t = performance.now(); const n = draw(g); drawMs += performance.now() - t; draws++; return n; };
      const decode = d._decode.bind(d);
      d._decode = async (i) => { const t = performance.now(); const g = await decode(i); decodeMs += performance.now() - t; decodes++; return g; };
      p.seek(0);
      await p.play();
      const s0 = { ...p.stats };
      const t0 = performance.now();
      await new Promise((res) => setTimeout(res, secs * 1000));
      const elapsed = (performance.now() - t0) / 1000;
      return {
        grid: `${p.m.columns}x${p.m.rows}`, canvas: `${r.canvas.width}x${r.canvas.height}`, cell: `${r.cw}x${r.ch}`,
        expectedFrames: Math.round(elapsed * p.decoder.fps), shown: p.stats.framesShown - s0.framesShown,
        skipped: p.stats.skipped - s0.skipped, avgDrawMs: +(drawMs / draws).toFixed(2), avgDecodeMs: +(decodeMs / decodes).toFixed(2),
        cellsDrawnPerFrame: Math.round((p.stats.drawn - s0.drawn) / Math.max(1, p.stats.framesShown - s0.framesShown)),
      };
    }, seconds);
    console.log(name, JSON.stringify(result));
    await browser.close();
  }
} finally {
  server.kill();
}
