// Atlas-based Canvas renderer.
//
// Every glyph is rasterised once, with the film's font, colours and device
// pixel ratio, into a tile of exactly one cell. Frames are drawn by copying
// tiles with drawImage at integer device-pixel positions, so glyphs stay crisp,
// never drift, and a changed cell can be redrawn on its own.
//
// Three atlases are kept:
//   opaque  — tile includes the background; used for normal frame updates
//   clear   — glyph only, transparent; used where glyphs may overlap
//   large   — glyph only at LARGE_SCALE x resolution; used for magnified glyphs
//
// An optional GlyphField (field.js) displaces and scales glyphs around the
// pointer. Only 8x8-cell blocks that hold moving glyphs are repainted.

import { BLOCK } from "./field.js";

const TILES_PER_ROW = 16;
const LARGE_SCALE = 3;
const SCALED_THRESHOLD = 1.06; // below this, draw the crisp 1x tile at a rounded position

export class AtlasRenderer {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {{columns:number, rows:number, font:object}} layout manifest fields
   * @param {string[]} glyphs glyph table from the film
   * @param {string} fontFamily loaded FontFace family name
   */
  constructor(canvas, layout, glyphs, fontFamily) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d", { alpha: false });
    this.columns = layout.columns;
    this.rows = layout.rows;
    this.font = layout.font;
    this.glyphs = glyphs;
    this.family = fontFamily;
    this.fg = "#eeeeee";
    this.bg = "#101010";
    this.prev = null;
    this.atlas = null;
    this.cw = this.ch = 0;
    this.field = null;
    this.fieldBlocks = null; // repaint blocks that held moving glyphs last frame
    this.lastStep = 0;
  }

  /** Attach a GlyphField (or null) for pointer interaction. */
  attachField(field) {
    this.field = field;
    if (field && this.cw) field.layout(this.cw, this.ch);
  }

  setTheme(foreground, background) {
    this.fg = foreground;
    this.bg = background;
    if (this.cw) this._buildAtlases();
    this.prev = null;
  }

  /** Fit the grid inside cssWidth x cssHeight CSS pixels at the given DPR. */
  resize(cssWidth, cssHeight, dpr) {
    const aspect = this.font.cellWidth / this.font.cellHeight; // cell width / height
    const availW = Math.max(1, cssWidth * dpr);
    const availH = Math.max(1, cssHeight * dpr);
    let cw = Math.max(1, Math.floor(Math.min(availW / this.columns, (availH / this.rows) * aspect)));
    let ch = Math.max(1, Math.round(cw / aspect));
    while (cw > 1 && (this.rows * ch > availH || this.columns * cw > availW)) {
      cw -= 1;
      ch = Math.max(1, Math.round(cw / aspect));
    }
    this.cw = cw;
    this.ch = ch;
    this.dpr = dpr;
    this.canvas.width = this.columns * cw;
    this.canvas.height = this.rows * ch;
    this.canvas.style.width = `${this.canvas.width / dpr}px`;
    this.canvas.style.height = `${this.canvas.height / dpr}px`;
    // Font size (device px) that makes one advance exactly one cell wide.
    this.fontPx = cw / (this.font.cellWidth / this.font.size);
    // Baseline sits where the encoder placed it: line box centred on ascent+descent.
    const f = this.font;
    this.baselineFrac = ((f.lineHeight - (f.ascent + f.descent)) / 2 + f.ascent) / f.lineHeight;
    this._buildAtlases();
    this.prev = null;
    this.fieldBlocks = null;
    if (this.field) this.field.layout(cw, ch);
  }

  _makeAtlas(scale, opaque) {
    const tw = this.cw * scale;
    const th = this.ch * scale;
    const n = this.glyphs.length;
    const w = tw * Math.min(n, TILES_PER_ROW);
    const h = th * Math.ceil(n / TILES_PER_ROW);
    const atlas = typeof OffscreenCanvas === "function"
      ? new OffscreenCanvas(w, h)
      : Object.assign(document.createElement("canvas"), { width: w, height: h });
    const a = atlas.getContext("2d", { alpha: !opaque });
    if (opaque) {
      a.fillStyle = this.bg;
      a.fillRect(0, 0, w, h);
    }
    a.fillStyle = this.fg;
    a.font = `${this.fontPx * scale}px "${this.family}"`;
    a.textBaseline = "alphabetic";
    a.textAlign = "left";
    for (let i = 1; i < n; i++) {
      const x = (i % TILES_PER_ROW) * tw;
      const y = Math.floor(i / TILES_PER_ROW) * th;
      a.save();
      a.beginPath();
      a.rect(x, y, tw, th);
      a.clip();
      a.fillText(this.glyphs[i], x, y + this.baselineFrac * th);
      a.restore();
    }
    return { canvas: atlas, tw, th };
  }

  _buildAtlases() {
    this.atlas = this._makeAtlas(1, true);
    this.clear = this._makeAtlas(1, false);
    this.large = this._makeAtlas(LARGE_SCALE, false);
    this.ctx.imageSmoothingEnabled = false;
  }

  /** Force the next draw to repaint every cell (seek, resize, theme, context loss). */
  invalidate() {
    this.prev = null;
  }

  /** Draw a glyph-index grid; only changed cells unless a full redraw is pending. */
  draw(grid) {
    const { ctx, atlas, cw, ch, columns } = this;
    if (!atlas) return 0;
    const prev = this.prev;
    let drawn = 0;
    if (!prev) {
      ctx.fillStyle = this.bg;
      ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    }
    const { canvas: img, tw, th } = atlas;
    for (let k = 0, n = grid.length; k < n; k++) {
      const g = grid[k];
      if (prev ? prev[k] === g : g === 0) continue; // background already painted
      const x = (k % columns) * cw;
      const y = ((k / columns) | 0) * ch;
      ctx.drawImage(img, (g % TILES_PER_ROW) * tw, ((g / TILES_PER_ROW) | 0) * th, tw, th, x, y, cw, ch);
      drawn++;
    }
    this.prev = grid;
    // Cells under the field were just drawn undisplaced; repaint that region.
    if (this.fieldBlocks || (this.field && this.field.bbox)) this._paintField();
    return drawn;
  }

  /**
   * Advance the field simulation to `now` (ms) and repaint its region.
   * Returns true while another animation frame is needed.
   */
  animate(now) {
    const field = this.field;
    if (!field || !this.prev) return false;
    const dt = this.lastStep ? (now - this.lastStep) / 1000 : 1 / 60;
    this.lastStep = now;
    const moving = field.step(dt);
    this._paintField();
    if (!moving) this.lastStep = 0;
    return moving || this.fieldBlocks !== null;
  }

  _paintField() {
    const field = this.field;
    const grid = this.prev;
    if (!field || !grid) return;
    const { ctx, cw, ch, columns, rows } = this;
    const cur = field.bbox ? field.blocks : null;
    const old = this.fieldBlocks;
    if (!cur && !old) return;
    // Repaint every block that holds a moving glyph now or held one last frame.
    const nb = field.blocks.length;
    const dirty = this.dirtyBlocks && this.dirtyBlocks.length === nb ? this.dirtyBlocks : (this.dirtyBlocks = new Uint8Array(nb));
    const bx = field.blocksX;
    const B = BLOCK;
    ctx.fillStyle = this.bg;
    let any = false;
    for (let b = 0; b < nb; b++) {
      dirty[b] = (cur && cur[b]) || (old && old[b]) ? 1 : 0;
      if (!dirty[b]) continue;
      any = true;
      const c0 = (b % bx) * B, r0 = ((b / bx) | 0) * B;
      ctx.fillRect(c0 * cw, r0 * ch, Math.min(B, columns - c0) * cw, Math.min(B, rows - r0) * ch);
    }
    if (!any) { this.fieldBlocks = null; return; }
    const { dx, dy, s } = field;
    const opaque = this.atlas;
    const small = this.clear;
    const big = this.large;
    const moved = [];
    const scaled = [];
    // Pass 1: glyphs at home, with opaque tiles (pixel-identical to a normal frame).
    for (let b = 0; b < nb; b++) {
      if (!dirty[b]) continue;
      const c0 = (b % bx) * B, r0 = ((b / bx) | 0) * B;
      const c1 = Math.min(c0 + B, columns), r1 = Math.min(r0 + B, rows);
      for (let r = r0; r < r1; r++) {
        for (let c = c0, i = r * columns + c0; c < c1; c++, i++) {
          const g = grid[i];
          if (g === 0) continue;
          if (field.moved[i]) { (s[i] >= SCALED_THRESHOLD ? scaled : moved).push(i); continue; }
          ctx.drawImage(opaque.canvas, (g % TILES_PER_ROW) * opaque.tw, ((g / TILES_PER_ROW) | 0) * opaque.th, cw, ch,
            c * cw, r * ch, cw, ch);
        }
      }
    }
    // Pass 2: displaced glyphs, transparent tiles so overlaps don't punch holes.
    for (const i of moved) {
      const g = grid[i];
      ctx.drawImage(small.canvas, (g % TILES_PER_ROW) * small.tw, ((g / TILES_PER_ROW) | 0) * small.th, cw, ch,
        (i % columns) * cw + Math.round(dx[i]), ((i / columns) | 0) * ch + Math.round(dy[i]), cw, ch);
    }
    // Pass 3: magnified glyphs last, so they sit on top of their squeezed neighbours.
    if (scaled.length) {
      ctx.imageSmoothingEnabled = true;
      scaled.sort((a, b) => s[a] - s[b]);
      for (const i of scaled) {
        const g = grid[i];
        const w = cw * s[i];
        const h = ch * s[i];
        const x = ((i % columns) + 0.5) * cw + dx[i] - w / 2;
        const y = (((i / columns) | 0) + 0.5) * ch + dy[i] - h / 2;
        ctx.drawImage(big.canvas, (g % TILES_PER_ROW) * big.tw, ((g / TILES_PER_ROW) | 0) * big.th, big.tw, big.th, x, y, w, h);
      }
      ctx.imageSmoothingEnabled = false;
    }
    this.fieldBlocks = cur ? (this.fieldBlocks && this.fieldBlocks.length === nb ? this.fieldBlocks : new Uint8Array(nb)) : null;
    if (cur) this.fieldBlocks.set(cur);
  }

  /**
   * Compare the loaded webfont's advance with the calibration metrics.
   * Returns the relative error (0.01 = 1%).
   */
  metricError() {
    const ctx = this.ctx;
    ctx.save();
    ctx.font = `100px "${this.family}"`;
    const measured = ctx.measureText("M").width / 100;
    ctx.restore();
    const expected = this.font.cellWidth / this.font.size;
    return Math.abs(measured - expected) / expected;
  }
}
