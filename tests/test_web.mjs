// Node built-in test runner:  node --test tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { AscfDecoder, AscfError, inflate } from "../web/decoder.js";

const here = new URL("./fixtures/", import.meta.url);
const bytes = readFileSync(new URL("tiny.ascf", here));
const expected = JSON.parse(readFileSync(new URL("tiny.expected.json", here), "utf8"));

const fresh = () => {
  const ab = new ArrayBuffer(bytes.length);
  new Uint8Array(ab).set(bytes);
  return ab;
};
const mutate = (fn) => {
  const ab = fresh();
  fn(new DataView(ab), new Uint8Array(ab));
  return ab;
};

test("header and glyph table", () => {
  const d = new AscfDecoder(fresh());
  assert.equal(d.columns, expected.columns);
  assert.equal(d.rows, expected.rows);
  assert.equal(d.frameCount, expected.frames.length);
  assert.deepEqual([d.fpsNum, d.fpsDen], expected.fps);
  assert.deepEqual(d.glyphs, expected.glyphs);
});

test("sequential decode matches the Python encoder", async () => {
  const d = new AscfDecoder(fresh());
  for (let i = 0; i < d.frameCount; i++) {
    assert.deepEqual(Array.from(await d.frame(i)), expected.frames[i], `frame ${i}`);
    assert.equal(d.types[i], expected.kinds[i]);
  }
});

test("random-order seeking (backward, forward, repeats)", async () => {
  const d = new AscfDecoder(fresh(), { keyframeCacheEntries: 2 });
  const order = [39, 0, 25, 24, 7, 8, 9, 33, 2, 39, 39, 15, 1];
  for (const i of order) assert.deepEqual(Array.from(await d.frame(i)), expected.frames[i], `frame ${i}`);
});

test("concurrent requests are serialised and correct", async () => {
  const d = new AscfDecoder(fresh());
  const idx = [5, 30, 1, 22, 39, 0];
  const grids = await Promise.all(idx.map((i) => d.frame(i)));
  idx.forEach((i, k) => assert.deepEqual(Array.from(grids[k]), expected.frames[i]));
});

test("returned grids are not mutated by later decodes", async () => {
  const d = new AscfDecoder(fresh());
  const g3 = await d.frame(3);
  const copy = Array.from(g3);
  await d.frame(4);
  await d.frame(5);
  assert.deepEqual(Array.from(g3), copy);
});

test("frameAt uses floor(t * num / den) with bounds", () => {
  const d = new AscfDecoder(fresh());
  assert.equal(d.frameAt(0), 0);
  assert.equal(d.frameAt(1001 / 30000), 1);
  assert.equal(d.frameAt(1001 / 30000 - 1e-6), 0);
  assert.equal(d.frameAt(-5), 0);
  assert.equal(d.frameAt(1e9), d.frameCount - 1);
  assert.equal(d.frameAt(d.durationSeconds / 2), Math.floor(d.frameCount / 2));
});

test("corrupt inputs fail with AscfError", async () => {
  const cases = {
    magic: mutate((v, u) => { u[0] = 0x58; }),
    version: mutate((v) => v.setUint16(4, 2, true)),
    fpsDen: mutate((v) => v.setUint32(28, 0, true)),
    truncated: fresh().slice(0, bytes.length - 7),
    tiny: fresh().slice(0, 20),
    indexOffset: mutate((v) => v.setBigUint64(48, 99999n, true)),
    glyphCount: mutate((v) => v.setUint32(36, 3, true)),
    utf8: mutate((v, u) => { u[68] = 0xff; }),
  };
  for (const [name, ab] of Object.entries(cases)) {
    assert.throws(() => new AscfDecoder(ab), AscfError, name);
  }
  // Corrupt a payload: structure parses, decoding fails cleanly.
  const d0 = new AscfDecoder(fresh());
  const off = d0.offsets[10];
  const bad = mutate((v, u) => { for (let k = 2; k < d0.clens[10]; k++) u[off + k] ^= 0x5a; });
  const d = new AscfDecoder(bad);
  await assert.rejects(() => d.frame(10), AscfError);
});

test("inflate rejects size mismatch", async () => {
  const d = new AscfDecoder(fresh());
  const payload = new Uint8Array(d.buffer, d.offsets[0], d.clens[0]);
  await assert.rejects(() => inflate(payload, d.ulens[0] - 1), AscfError);
  await assert.rejects(() => inflate(payload, d.ulens[0] + 1), AscfError);
});
