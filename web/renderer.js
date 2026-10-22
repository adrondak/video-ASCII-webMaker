// Checkpoint 04 renderer: the simplest correct approach — one fillText per row.
export class TextRenderer {
  constructor(canvas, manifest, glyphs) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.m = manifest;
    this.glyphs = glyphs;
  }

  resize() {
    const { columns, rows, font } = this.m;
    const dpr = window.devicePixelRatio || 1;
    const scale = Math.min(innerWidth / (columns * font.cellWidth), innerHeight / (rows * font.cellHeight));
    const w = columns * font.cellWidth * scale;
    const h = rows * font.cellHeight * scale;
    this.canvas.style.width = `${w}px`;
    this.canvas.style.height = `${h}px`;
    this.canvas.width = Math.round(w * dpr);
    this.canvas.height = Math.round(h * dpr);
    this.px = font.size * scale * dpr;
    this.lineH = font.cellHeight * scale * dpr;
    this.baseline = (font.lineHeight - (font.ascent + font.descent)) / 2 * this.px + font.ascent * this.px;
  }

  draw(grid) {
    const { ctx, m } = this;
    ctx.fillStyle = m.theme.background;
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    ctx.fillStyle = m.theme.foreground;
    ctx.font = `${this.px}px ASCIIFilmFont`;
    ctx.textBaseline = "alphabetic";
    for (let r = 0; r < m.rows; r++) {
      let line = "";
      for (let c = 0; c < m.columns; c++) line += this.glyphs[grid[r * m.columns + c]];
      ctx.fillText(line, 0, r * this.lineH + this.baseline);
    }
  }
}
