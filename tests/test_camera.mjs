// Node tests for the live mapping:  node --test tests/test_camera.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { LiveMapper, liveRows, srgbEncode } from "../web/camera.js";

// A plausible calibrated coverage table (ascending, space = 0).
const COVERAGE = [0, 0.09, 0.15, 0.19, 0.25, 0.39, 0.52, 0.56, 0.66, 0.69, 0.72, 0.73, 0.79, 0.8, 0.85, 0.86, 0.9, 0.96, 1];
const COLS = 20, ROWS = 10;

const mapper = (o = {}) => new LiveMapper({ columns: COLS, rows: ROWS, coverage: COVERAGE, inkLight: true,
  autoLevels: false, variation: 0, stability: 0, ...o });

function frame(m, fn) {
  const w = m.sampleWidth, h = m.sampleHeight;
  const px = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const v = fn(x / (w - 1), y / (h - 1));
    const p = (y * w + x) * 4;
    px[p] = px[p + 1] = px[p + 2] = v;
    px[p + 3] = 255;
  }
  return px;
}

test("black maps to space, white to the densest glyph", () => {
  const m = mapper();
  const out = new Uint8Array(COLS * ROWS);
  assert.ok(m.map(frame(m, () => 0), out).every((g) => g === 0));
  const m2 = mapper();
  assert.ok(m2.map(frame(m2, () => 255), new Uint8Array(COLS * ROWS)).every((g) => g === COVERAGE.length - 1));
});

test("polarity follows the theme and invert", () => {
  const dark = mapper({ inkLight: false });
  assert.ok(dark.map(frame(dark, () => 255), new Uint8Array(COLS * ROWS)).every((g) => g === 0));
  const inv = mapper({ invert: true });
  assert.ok(inv.map(frame(inv, () => 0), new Uint8Array(COLS * ROWS)).every((g) => g === COVERAGE.length - 1));
});

test("a horizontal gradient maps to non-decreasing coverage", () => {
  const m = mapper();
  const out = m.map(frame(m, (x) => Math.round(x * 255)), new Uint8Array(COLS * ROWS));
  for (let r = 0; r < ROWS; r++) {
    for (let c = 1; c < COLS; c++) assert.ok(COVERAGE[out[r * COLS + c]] >= COVERAGE[out[r * COLS + c - 1]]);
  }
});

test("cells average linear light (half white = 50% linear)", () => {
  const m = new LiveMapper({ columns: 1, rows: 1, coverage: COVERAGE, inkLight: true, autoLevels: false });
  const px = new Uint8ClampedArray(4 * 8 * 4);
  for (let p = 0; p < px.length; p += 4) { const x = (p / 4) % 4; px[p] = px[p + 1] = px[p + 2] = x < 2 ? 255 : 0; px[p + 3] = 255; }
  assert.ok(Math.abs(m.analyze(px)[0] - srgbEncode(0.5)) < 1e-3);
});

test("hysteresis suppresses flicker from sensor noise; cuts reset", () => {
  const run = (stability) => {
    const m = mapper({ stability });
    const bufs = [new Uint8Array(COLS * ROWS), new Uint8Array(COLS * ROWS)];
    let changes = 0, prev = null, seed = 7;
    const noise = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
    for (let f = 0; f < 40; f++) {
      // Frame-wide exposure wobble right at the 0.52/0.56 glyph boundary (tone 0.54).
      const level = 138 + Math.round((noise() - 0.5) * 6);
      const out = m.map(frame(m, () => level), bufs[f % 2]);
      if (prev) for (let i = 0; i < out.length; i++) changes += out[i] !== prev[i];
      prev = Uint8Array.from(out);
    }
    return { changes, m };
  };
  const raw = run(0).changes, stable = run(0.35).changes;
  assert.ok(stable < raw * 0.3, `stable ${stable} vs raw ${raw}`);
  const { m } = run(0.35);
  m.map(frame(m, () => 0), new Uint8Array(COLS * ROWS));
  assert.equal(m.cuts, 1);
});

test("variation mixes similar glyphs in flat areas, deterministically", () => {
  const a = mapper({ variation: 1.5, seed: 3 }), b = mapper({ variation: 1.5, seed: 3 });
  const fa = a.map(frame(a, () => 225), new Uint8Array(COLS * ROWS));
  const fb = b.map(frame(b, () => 225), new Uint8Array(COLS * ROWS));
  assert.deepEqual(Array.from(fa), Array.from(fb));
  assert.ok(new Set(fa).size > 1);
});

test("rows follow the camera aspect and the measured cell", () => {
  assert.equal(liveRows(160, 1280, 720, 12.04, 23.3), Math.round(160 * 720 / 1280 * 12.04 / 23.3));
  assert.equal(liveRows(100, 720, 1280, 12.04, 20), Math.round(100 * 1280 / 720 * 12.04 / 20));
  assert.equal(liveRows(320, 100, 10000, 12, 20), 240); // clamped
});
