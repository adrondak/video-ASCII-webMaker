// Interactive glyph field: physics for the cursor lens and ripples.
//
// Every cell is a damped spring anchored at its grid position, with a
// position offset (dx, dy) and a scale s. Three things drive the springs:
//
// * The lens: near the pointer each cell's *target* is pushed outward along a
//   Gaussian bulge, d' = d * (1 + A * exp(-d²/R²)), and its target scale grows
//   by the same local magnification. Glyphs part around the cursor and swell
//   in the middle, so the bulge doubles as a magnifier.
// * Ripples: pointer movement emits expanding rings; a ring pushes cells
//   outward and swells them as it passes, fading with age and distance.
// * Springs: underdamped (damping ratio ~0.22) with a little per-cell
//   stiffness variation, so glyphs lag, overshoot and wag back into place
//   when the cursor moves on.
//
// Pure module (no DOM): positions are in canvas device pixels. The renderer
// paints the result; tests drive it directly.

export const FIELD_DEFAULTS = Object.freeze({
  lens: true,
  lensRadius: 7, // in cell widths
  lensStrength: 1.4, // A: centre magnification is 1 + A (keep < 2.2 to stay monotonic)
  ripples: true,
  rippleStrength: 1, // multiplier on ripple push and swell
});

const STIFFNESS = 170; // s^-2  (natural frequency ~2 Hz)
const DAMPING_RATIO = 0.22; // < 1: underdamped, so glyphs wag
const SCALE_GAIN = 0.75; // how much of the radial magnification shows as glyph scale
const RIPPLE_SPEED = 26; // cells per second
const RIPPLE_WIDTH = 1.6; // cells (Gaussian width of the ring)
const RIPPLE_LIFE = 2.6; // seconds
const RIPPLE_DECAY = 1.1; // seconds (amplitude e-folding time)
const RIPPLE_ACCEL = 300; // cell widths per s^2 at strength 1
const RIPPLE_SCALE_KICK = 0.06; // scale acceleration per unit of ring force (per cell width)
const MAX_RIPPLES = 6;
const EMIT_DISTANCE = 3; // cells moved before another ripple is emitted
const EMIT_INTERVAL = 0.16; // seconds between ripples at most
const REST = 0.02; // device px / scale units below which a spring is at rest
const VISIBLE_SCALE = 0.004; // scale change below this draws exactly like the resting glyph
const MAX_DT = 1 / 30;
export const BLOCK = 8; // cells per side of a repaint block

function hash01(i) {
  // Deterministic per-cell jitter in [0, 1).
  let x = (i + 1) * 0x9e3779b1;
  x ^= x >>> 15;
  x = Math.imul(x, 0x85ebca77);
  x ^= x >>> 13;
  return (x >>> 0) / 4294967296;
}

export class GlyphField {
  constructor(columns, rows, options = {}) {
    this.columns = columns;
    this.rows = rows;
    this.opts = { ...FIELD_DEFAULTS, ...options };
    const n = columns * rows;
    this.dx = new Float32Array(n);
    this.dy = new Float32Array(n);
    this.vx = new Float32Array(n);
    this.vy = new Float32Array(n);
    this.s = new Float32Array(n).fill(1);
    this.vs = new Float32Array(n);
    this.live = new Uint8Array(n); // 1 while a cell's spring is not at rest
    this.moved = new Uint8Array(n); // 1 while a cell is drawn away from its resting tile
    this.stiff = new Float32Array(n);
    for (let i = 0; i < n; i++) this.stiff[i] = STIFFNESS * (0.8 + 0.45 * hash01(i));
    this.ripples = [];
    this.pointer = null; // { x, y }
    this.lastEmit = null; // { x, y, t }
    this.time = 0;
    this.enabled = true;
    this.bbox = null; // affected cells this step: { c0, r0, c1, r1 } (inclusive)
    this.blocksX = Math.ceil(columns / BLOCK);
    this.blocksY = Math.ceil(rows / BLOCK);
    this.blocks = new Uint8Array(this.blocksX * this.blocksY); // 1 = contains moving glyphs
    this.layout(1, 1);
  }

  /** Cell size in device pixels; resets all motion. */
  layout(cw, ch) {
    this.cw = cw;
    this.ch = ch;
    this.R = this.opts.lensRadius * cw;
    this.reset();
  }

  reset() {
    this.dx.fill(0); this.dy.fill(0); this.vx.fill(0); this.vy.fill(0);
    this.s.fill(1); this.vs.fill(0); this.live.fill(0); this.moved.fill(0);
    this.ripples = [];
    this.bbox = null;
    this.liveCount = 0;
    if (this.blocks) this.blocks.fill(0);
  }

  setEnabled(on) {
    this.enabled = on;
    if (!on) this.pointer = null;
  }

  /** Pointer at (x, y) device px at time t (seconds). Emits ripples as it moves. */
  setPointer(x, y, t = this.time) {
    if (!this.enabled) return;
    this.pointer = { x, y };
    if (!this.opts.ripples) return;
    const e = this.lastEmit;
    if (!e) { this.lastEmit = { x, y, t }; return; }
    const dist = Math.hypot(x - e.x, y - e.y) / this.cw;
    const dt = t - e.t;
    if (dist >= EMIT_DISTANCE && dt >= EMIT_INTERVAL) {
      const speed = dist / dt; // cells per second
      this.pulse(x, y, Math.min(1, Math.max(0.15, speed / 60)), t);
      this.lastEmit = { x, y, t };
    }
  }

  clearPointer() {
    this.pointer = null;
    this.lastEmit = null;
  }

  /** Emit a ripple ring from (x, y) with relative strength (1 = fast swipe). */
  pulse(x, y, strength = 1, t = this.time) {
    if (!this.enabled || !this.opts.ripples) return;
    this.ripples.push({ x, y, t0: t, amp: strength * this.opts.rippleStrength });
    if (this.ripples.length > MAX_RIPPLES) this.ripples.shift();
  }

  get active() {
    return this.bbox !== null || this.pointer !== null || this.ripples.length > 0 || this.liveCount > 0;
  }

  /** Advance the simulation by dt seconds. Returns true while anything moves. */
  step(dt) {
    dt = Math.min(Math.max(dt, 0), MAX_DT);
    this.time += dt;
    const { columns, rows, cw, ch, dx, dy, vx, vy, s, vs, live, moved, stiff } = this;
    const now = this.time;
    this.ripples = this.ripples.filter((r) => now - r.t0 < RIPPLE_LIFE);

    const lens = this.enabled && this.opts.lens && this.pointer;
    const A = this.opts.lensStrength;
    const R = this.R;
    const invR2 = 1 / (R * R);
    const reach2 = 9 * R * R; // exp(-9) is negligible beyond 3R
    const px = lens ? this.pointer.x : 0;
    const py = lens ? this.pointer.y : 0;

    const rings = this.ripples.map((r) => {
      const age = now - r.t0;
      const radius = age * RIPPLE_SPEED * cw;
      const spread = 1 / Math.sqrt(1 + radius / (12 * cw));
      return { x: r.x, y: r.y, radius, w: RIPPLE_WIDTH * cw, amp: r.amp * RIPPLE_ACCEL * cw * Math.exp(-age / RIPPLE_DECAY) * spread };
    });

    let c0 = Infinity, r0 = Infinity, c1 = -1, r1 = -1;
    let liveCount = 0;
    const blocks = this.blocks;
    const bx = this.blocksX;
    blocks.fill(0);
    const damp = 2 * DAMPING_RATIO;
    for (let r = 0, i = 0; r < rows; r++) {
      const cy = (r + 0.5) * ch;
      for (let c = 0; c < columns; c++, i++) {
        const cx = (c + 0.5) * cw;
        let tx = 0, ty = 0, ts = 1, fx = 0, fy = 0, fs = 0;
        let driven = false;
        if (lens) {
          const rx = cx - px, ry = cy - py;
          const d2 = rx * rx + ry * ry;
          if (d2 < reach2) {
            const e = Math.exp(-d2 * invR2);
            tx = A * rx * e;
            ty = A * ry * e;
            ts = 1 + A * SCALE_GAIN * e;
            driven = e > 1e-4;
          }
        }
        for (let k = 0; k < rings.length; k++) {
          const g = rings[k];
          const rx = cx - g.x, ry = cy - g.y;
          const d = Math.sqrt(rx * rx + ry * ry) || 1;
          const off = (d - g.radius) / g.w;
          if (off > -3 && off < 3) {
            const f = g.amp * Math.exp(-off * off);
            fx += (f * rx) / d;
            fy += (f * ry) / d;
            fs += (f / cw) * RIPPLE_SCALE_KICK;
            driven = true;
          }
        }
        if (!driven && !live[i]) continue;

        const k = stiff[i];
        const cdamp = damp * Math.sqrt(k);
        vx[i] += (k * (tx - dx[i]) - cdamp * vx[i] + fx) * dt;
        vy[i] += (k * (ty - dy[i]) - cdamp * vy[i] + fy) * dt;
        vs[i] += (k * (ts - s[i]) - cdamp * vs[i] + fs) * dt;
        dx[i] += vx[i] * dt;
        dy[i] += vy[i] * dt;
        s[i] += vs[i] * dt;

        if (!driven && Math.abs(dx[i]) < REST && Math.abs(dy[i]) < REST && Math.abs(vx[i]) < REST
            && Math.abs(vy[i]) < REST && Math.abs(s[i] - 1) < REST * 0.05 && Math.abs(vs[i]) < REST * 0.05) {
          dx[i] = dy[i] = vx[i] = vy[i] = vs[i] = 0;
          s[i] = 1;
          live[i] = 0;
          moved[i] = 0;
          continue;
        }
        live[i] = 1;
        liveCount++;
        // Sub-pixel wobble draws exactly like the resting glyph: no repaint needed.
        if (Math.round(dx[i]) === 0 && Math.round(dy[i]) === 0 && Math.abs(s[i] - 1) < VISIBLE_SCALE) {
          moved[i] = 0;
          continue;
        }
        moved[i] = 1;
        // Bounding box (in cells) of where this glyph is drawn now, plus its home cell.
        const half = 0.5 * Math.max(s[i], 1);
        const gx0 = Math.floor((cx + dx[i]) / cw - half), gx1 = Math.floor((cx + dx[i]) / cw + half);
        const gy0 = Math.floor((cy + dy[i]) / ch - half), gy1 = Math.floor((cy + dy[i]) / ch + half);
        const a0 = Math.max(0, Math.min(gx0, c)), a1 = Math.min(columns - 1, Math.max(gx1, c));
        const b0 = Math.max(0, Math.min(gy0, r)), b1 = Math.min(rows - 1, Math.max(gy1, r));
        if (a0 < c0) c0 = a0;
        if (a1 > c1) c1 = a1;
        if (b0 < r0) r0 = b0;
        if (b1 > r1) r1 = b1;
        for (let by = (b0 / BLOCK) | 0, byEnd = (b1 / BLOCK) | 0; by <= byEnd; by++) {
          for (let bxi = (a0 / BLOCK) | 0, bxEnd = (a1 / BLOCK) | 0; bxi <= bxEnd; bxi++) blocks[by * bx + bxi] = 1;
        }
      }
    }
    this.bbox = c1 < 0 ? null : { c0, r0, c1, r1 };
    this.liveCount = liveCount;
    return this.active;
  }
}
