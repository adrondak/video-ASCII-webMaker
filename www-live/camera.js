// Live image -> glyph mapping: the encoder's pipeline (encoder/mapping.py and
// encoder/temporal.py) ported to JavaScript so it can run on webcam frames.
//
// Per frame:
//   1. RGBA pixels at (columns*ox) x (rows*oy) -> linear-light luminance,
//      averaged per character cell, re-encoded to perceptual sRGB tone.
//   2. Live auto-levels: tone percentiles per frame, smoothed over ~0.5 s so
//      exposure changes glide instead of pumping.
//   3. Tone curve (contrast, brightness, gamma) and theme polarity -> ink target.
//   4. Light low-pass + hysteresis against the previous frame (reset on cuts).
//   5. Nearest glyph by *measured* ink coverage, plus a static seeded per-cell
//      offset (variation / ordered dither) so flat areas get mixed glyphs.
//
// Pure module: no DOM. Glyph coverage comes from the encoder's calibration
// (live.json), so live output matches encoded films exactly in tone.

const SRGB_LINEAR = new Float32Array(256);
for (let v = 0; v < 256; v++) {
  const c = v / 255;
  SRGB_LINEAR[v] = c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}
const LR = SRGB_LINEAR.map((x) => 0.2126 * x);
const LG = SRGB_LINEAR.map((x) => 0.7152 * x);
const LB = SRGB_LINEAR.map((x) => 0.0722 * x);
const BAYER4 = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5].map((v) => (v + 0.5) / 16 - 0.5);

export function srgbEncode(linear) {
  const l = Math.min(Math.max(linear, 0), 1);
  return l <= 0.0031308 ? l * 12.92 : 1.055 * l ** (1 / 2.4) - 0.055;
}

export function hexLuminance(hex) {
  const v = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return LR[v[0]] + LG[v[1]] + LB[v[2]];
}

function hash01(i, seed) {
  let x = Math.imul((i + 1) ^ Math.imul(seed + 1, 0x27d4eb2d), 0x9e3779b1);
  x ^= x >>> 15;
  x = Math.imul(x, 0x85ebca77);
  x ^= x >>> 13;
  return (x >>> 0) / 4294967296;
}

export const LIVE_DEFAULTS = Object.freeze({
  oversampleX: 4,
  oversampleY: 8,
  brightness: 0,
  contrast: 1,
  gamma: 1,
  invert: false,
  autoLevels: true,
  levelsLowPercentile: 0.5,
  levelsHighPercentile: 99.5,
  levelsSmoothing: 0.08, // fraction of the new measurement blended in per frame
  variation: 0.35,
  dither: 0,
  seed: 1,
  stability: 0.25,
  cutThreshold: 0.22,
});

export class LiveMapper {
  /**
   * @param {object} o
   * @param {number} o.columns
   * @param {number} o.rows
   * @param {ArrayLike<number>} o.coverage normalised glyph coverage, ascending, coverage[0] = 0 (space)
   * @param {boolean} o.inkLight true when glyphs are lighter than the background
   */
  constructor(o) {
    this.o = { ...LIVE_DEFAULTS, ...o };
    const { columns, rows } = this.o;
    this.columns = columns;
    this.rows = rows;
    this.cells = columns * rows;
    this.coverage = Float32Array.from(this.o.coverage);
    const g = this.coverage.length;
    this.midpoints = new Float32Array(g - 1);
    for (let k = 0; k < g - 1; k++) this.midpoints[k] = (this.coverage[k] + this.coverage[k + 1]) / 2;
    const step = 1 / Math.max(g - 1, 1);
    this.offset = new Float32Array(this.cells);
    for (let r = 0, i = 0; r < rows; r++) {
      for (let c = 0; c < columns; c++, i++) {
        this.offset[i] = (hash01(i, this.o.seed) - 0.5) * this.o.variation * step
          + BAYER4[(r % 4) * 4 + (c % 4)] * this.o.dither * step;
      }
    }
    this.tone = new Float32Array(this.cells);
    this.target = new Float32Array(this.cells);
    this.smoothed = new Float32Array(this.cells);
    this.raw = new Float32Array(this.cells);
    this.hist = new Uint32Array(256);
    this.levels = null; // [low, high] once measured
    this.hasPrev = false;
    this.prevGrid = null;
    this.alpha = 0.5 * this.o.stability;
    this.margin = 0.1 * this.o.stability;
    this.cuts = 0;
  }

  get sampleWidth() { return this.columns * this.o.oversampleX; }
  get sampleHeight() { return this.rows * this.o.oversampleY; }

  /** Cell tones (perceptual 0..1) from RGBA pixels of size sampleWidth x sampleHeight. */
  analyze(rgba) {
    const { columns, rows, cells } = this;
    const ox = this.o.oversampleX, oy = this.o.oversampleY;
    const w = columns * ox;
    const sums = this.tone; // reuse as accumulator
    sums.fill(0);
    for (let y = 0; y < rows * oy; y++) {
      const rowBase = ((y / oy) | 0) * columns;
      let p = y * w * 4;
      for (let c = 0; c < columns; c++) {
        let acc = 0;
        for (let k = 0; k < ox; k++, p += 4) acc += LR[rgba[p]] + LG[rgba[p + 1]] + LB[rgba[p + 2]];
        sums[rowBase + c] += acc;
      }
    }
    const inv = 1 / (ox * oy);
    for (let i = 0; i < cells; i++) sums[i] = srgbEncode(sums[i] * inv);
    return sums;
  }

  _updateLevels(tone) {
    const o = this.o;
    if (!o.autoLevels) { this.levels = [0, 1]; return; }
    const hist = this.hist;
    hist.fill(0);
    for (let i = 0; i < tone.length; i++) hist[Math.min(255, (tone[i] * 256) | 0)]++;
    const pick = (pct) => {
      const goal = (pct / 100) * tone.length;
      let acc = 0;
      for (let b = 0; b < 256; b++) { acc += hist[b]; if (acc >= goal) return b / 256; }
      return 1;
    };
    let low = pick(o.levelsLowPercentile);
    let high = pick(o.levelsHighPercentile) + 1 / 256;
    if (high - low < 0.05) { low = 0; high = 1; }
    if (!this.levels) { this.levels = [low, high]; return; }
    const k = o.levelsSmoothing;
    this.levels = [this.levels[0] + (low - this.levels[0]) * k, this.levels[1] + (high - this.levels[1]) * k];
  }

  /**
   * Map one frame of RGBA pixels to glyph indices.
   * @param {Uint8ClampedArray|Uint8Array} rgba sampleWidth x sampleHeight x 4
   * @param {Uint8Array} out receives `cells` glyph indices (must not be the array returned last time)
   */
  map(rgba, out) {
    const o = this.o;
    const tone = this.analyze(rgba);
    this._updateLevels(tone);
    const [low, high] = this.levels;
    const span = Math.max(high - low, 1e-6);
    const flip = o.inkLight === o.invert;
    const target = this.target;
    let diff = 0;
    for (let i = 0; i < this.cells; i++) {
      let t = (tone[i] - low) / span;
      t = (t - 0.5) * o.contrast + 0.5 + o.brightness;
      t = t < 0 ? 0 : t > 1 ? 1 : t;
      if (o.gamma !== 1) t = t ** o.gamma;
      if (flip) t = 1 - t;
      if (this.hasPrev) diff += Math.abs(t - this.raw[i]);
      target[i] = t;
    }
    // Hard cut (or first frame): no smoothing, no held glyphs.
    const cut = !this.hasPrev || diff / this.cells > o.cutThreshold;
    if (cut && this.hasPrev) this.cuts++;
    this.raw.set(target);
    const smoothed = this.smoothed;
    const prev = cut ? null : this.prevGrid;
    const a = cut ? 0 : this.alpha;
    const cov = this.coverage, mids = this.midpoints, nm = mids.length;
    for (let i = 0; i < this.cells; i++) {
      const s = a > 0 ? a * smoothed[i] + (1 - a) * target[i] : target[i];
      smoothed[i] = s;
      const t = s + this.offset[i];
      // Nearest coverage: binary search over midpoints.
      let lo = 0, hi = nm;
      while (lo < hi) { const m = (lo + hi) >> 1; if (mids[m] < t) lo = m + 1; else hi = m; }
      let g = lo;
      if (prev && this.margin > 0) {
        const keep = prev[i];
        if (Math.abs(t - cov[keep]) <= Math.abs(t - cov[g]) + this.margin) g = keep;
      }
      out[i] = g;
    }
    this.hasPrev = true;
    this.prevGrid = out;
    return out;
  }
}

/** Rows for a camera frame: rows = round(columns * h / w * cellWidth / cellHeight). */
export function liveRows(columns, width, height, cellWidth, cellHeight, minRows = 8, maxRows = 240) {
  const rows = Math.round((columns * height / width) * (cellWidth / cellHeight));
  return Math.min(Math.max(rows, minRows), maxRows);
}
