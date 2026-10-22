// Node tests for the glyph-field physics:  node --test tests/test_field.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { GlyphField } from "../web/field.js";

const CW = 10, CH = 20, COLS = 60, ROWS = 30;
const make = (opts) => { const f = new GlyphField(COLS, ROWS, opts); f.layout(CW, CH); return f; };
const idx = (c, r) => r * COLS + c;
const run = (f, seconds, fn) => { for (let t = 0; t < seconds; t += 1 / 60) { f.step(1 / 60); if (fn) fn(); } };
const centre = (c, r) => [(c + 0.5) * CW, (r + 0.5) * CH];

test("lens pushes glyphs outward and magnifies the middle", () => {
  const f = make({ ripples: false });
  f.setPointer(...centre(30, 15));
  run(f, 2);
  const right = idx(33, 15), left = idx(27, 15), below = idx(30, 17), far = idx(5, 2);
  assert.ok(f.dx[right] > 5, `right moves right (${f.dx[right]})`);
  assert.ok(f.dx[left] < -5, "left moves left");
  assert.ok(f.dy[below] > 5, "below moves down");
  assert.ok(f.s[idx(30, 15)] > 1.8, `centre is magnified (${f.s[idx(30, 15)]})`);
  assert.equal(f.dx[far], 0);
  assert.ok(f.bbox && f.bbox.c0 > 0 && f.bbox.c1 < COLS - 1, "only a local region is affected");
});

test("released glyphs wag (overshoot) and come fully to rest", () => {
  const f = make({ ripples: false });
  f.setPointer(...centre(30, 15));
  run(f, 2);
  const i = idx(33, 15);
  f.clearPointer();
  let min = Infinity;
  run(f, 1.5, () => { min = Math.min(min, f.dx[i]); });
  assert.ok(min < -1, `overshoots past home (min dx ${min.toFixed(2)})`);
  run(f, 6);
  assert.equal(f.dx[i], 0);
  assert.equal(f.s[i], 1);
  assert.equal(f.active, false);
  assert.equal(f.bbox, null);
});

test("moving the pointer emits ripples that travel and fade", () => {
  const f = make({ lens: false });
  for (let k = 0; k < 10; k++) { f.setPointer(100 + k * 40, 300, k * 0.08); f.step(0.08); }
  assert.ok(f.ripples.length > 0);
  const probe = idx(45, 25);
  let peak = 0;
  run(f, 2, () => { peak = Math.max(peak, Math.hypot(f.dx[probe], f.dy[probe])); });
  assert.ok(peak > 0.5, `a distant glyph is nudged by the ring (${peak.toFixed(2)} px)`);
  f.clearPointer();
  run(f, 8);
  assert.equal(f.active, false);
});

test("click pulse, disable and determinism", () => {
  const a = make(), b = make();
  for (const f of [a, b]) { f.pulse(...centre(10, 10), 1.6); run(f, 0.5); }
  assert.deepEqual(Array.from(a.dx), Array.from(b.dx));
  const off = make();
  off.setEnabled(false);
  off.setPointer(...centre(30, 15));
  off.pulse(...centre(30, 15));
  run(off, 1);
  assert.equal(off.active, false);
});
