// Atlas-based Canvas renderer.
//
// Every glyph is rasterised once, with the film's font, colours and device
// pixel ratio, into an opaque tile of exactly one cell. Frames are drawn by
// copying tiles with drawImage at integer device-pixel positions, so glyphs
// stay crisp, never drift, and a changed cell can be redrawn on its own.

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
  }

  setTheme(foreground, background) {
    this.fg = foreground;
    this.bg = background;
    if (this.cw) this._buildAtlas();
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
    this.baseline = (((f.lineHeight - (f.ascent + f.descent)) / 2 + f.ascent) / f.lineHeight) * ch;
    this._buildAtlas();
    this.prev = null;
  }

  _buildAtlas() {
    const { cw, ch } = this;
    const n = this.glyphs.length;
    const atlas = typeof OffscreenCanvas === "function"
      ? new OffscreenCanvas(cw * n, ch)
      : Object.assign(document.createElement("canvas"), { width: cw * n, height: ch });
    const a = atlas.getContext("2d", { alpha: false });
    a.fillStyle = this.bg;
    a.fillRect(0, 0, cw * n, ch);
    a.fillStyle = this.fg;
    a.font = `${this.fontPx}px "${this.family}"`;
    a.textBaseline = "alphabetic";
    a.textAlign = "left";
    for (let i = 1; i < n; i++) {
      a.save();
      a.beginPath();
      a.rect(i * cw, 0, cw, ch);
      a.clip();
      a.fillText(this.glyphs[i], i * cw, this.baseline);
      a.restore();
    }
    this.atlas = atlas;
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
    for (let k = 0, n = grid.length; k < n; k++) {
      const g = grid[k];
      if (prev ? prev[k] === g : g === 0) continue; // background already painted
      const x = (k % columns) * cw;
      const y = ((k / columns) | 0) * ch;
      ctx.drawImage(atlas, g * cw, 0, cw, ch, x, y, cw, ch);
      drawn++;
    }
    this.prev = grid;
    return drawn;
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
