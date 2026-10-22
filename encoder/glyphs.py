"""Font measurement and glyph ink-coverage calibration.

Every candidate glyph is rendered with the selected font into a bitmap the
size of one character cell, exactly as the player will place it (left edge,
alphabetic baseline centred in the line box). Its average ink is its
*coverage*. Glyphs are sorted by measured coverage — never by literal ASCII
order — and coverage is normalised so space is 0.0 and the densest glyph 1.0.

Each glyph also gets a small *shape pattern* (its bitmap area-averaged down to
the sampling sub-grid, zero-mean, unit length) used by the optional detail
weighting in :mod:`encoder.mapping`.
"""

from __future__ import annotations

import string
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .errors import EncodeError

METRIC_SIZE = 1000  # px size used to derive em-relative metrics precisely
CALIBRATION_SCALE = 3  # glyphs are rendered at font_size * this for calibration
MAX_GLYPHS = 256
_MISSING_PROBE = "\U0010fffd"  # private-use codepoint no font should map


@dataclass(frozen=True)
class FontMetrics:
    path: str
    family: str
    style: str
    size: float  # reference font size in px
    advance_em: float  # cell width / font size
    ascent_em: float
    descent_em: float
    line_height_em: float  # cell height / font size

    @property
    def cell_width(self) -> float:
        return self.advance_em * self.size

    @property
    def cell_height(self) -> float:
        return self.line_height_em * self.size

    @property
    def cell_aspect(self) -> float:
        """Cell width divided by cell height."""
        return self.advance_em / self.line_height_em

    @property
    def baseline_em(self) -> float:
        """Distance from the top of the cell to the baseline, in em."""
        return (self.line_height_em - (self.ascent_em + self.descent_em)) / 2 + self.ascent_em


@dataclass(frozen=True)
class GlyphSet:
    chars: list[str]  # sorted by coverage; chars[0] == " "
    coverage: np.ndarray  # (G,) float32, normalised 0..1
    raw_coverage: np.ndarray  # (G,) float32, fraction of the cell covered by ink
    patterns: np.ndarray  # (G, oy*ox) float32 zero-mean, unit-length shape descriptors
    metrics: FontMetrics

    def __len__(self) -> int:
        return len(self.chars)


def parse_glyphs(text: str) -> list[str]:
    """Validate a glyph string: unique, single-codepoint, printable, non-combining.

    The space glyph is always included (it is reserved as index 0).
    """
    out: list[str] = []
    seen: set[str] = set()
    for ch in text:
        if ch in seen:
            continue
        seen.add(ch)
        cat = unicodedata.category(ch)
        if ch != " " and (cat.startswith("C") or cat.startswith("Z")):
            raise EncodeError(f"glyph U+{ord(ch):04X} is a control/space/format character")
        if cat in ("Mn", "Mc", "Me") or unicodedata.combining(ch):
            raise EncodeError(f"glyph U+{ord(ch):04X} is a combining mark; v1 needs standalone glyphs")
        if 0xD800 <= ord(ch) <= 0xDFFF:
            raise EncodeError(f"glyph U+{ord(ch):04X} is a surrogate")
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            raise EncodeError(f"glyph {ch!r} is double-width and cannot sit in one cell")
        out.append(ch)
    if " " not in seen:
        out.insert(0, " ")
    if len(out) > MAX_GLYPHS:
        raise EncodeError(f"at most {MAX_GLYPHS} glyphs are supported (got {len(out)})")
    if len(out) < 2:
        raise EncodeError("need at least one glyph besides space")
    return out


def load_font(path: str | Path, size: float) -> ImageFont.FreeTypeFont:
    p = Path(path)
    if not p.is_file():
        raise EncodeError(f"font not found: {p}")
    try:
        return ImageFont.truetype(str(p), size=size)
    except OSError as exc:
        raise EncodeError(f"cannot load font {p}: {exc}") from None


def measure_font(path: str | Path, size: float, line_height: float | None,
                 glyphs: list[str], allow_proportional: bool = False) -> FontMetrics:
    font = load_font(path, METRIC_SIZE)
    advances = {ch: font.getlength(ch) for ch in set(string.printable[:95]) | set(glyphs)}
    adv = advances["M"]
    spread = max(abs(a - adv) for ch, a in advances.items() if ch in glyphs or ch in "Mil.W ")
    if spread > METRIC_SIZE * 0.002 and not allow_proportional:
        raise EncodeError(f"font {path} is not fixed-pitch (advance widths differ by "
                          f"{spread / METRIC_SIZE:.3f} em); pass --allow-proportional-font "
                          "to override")
    ascent, descent = font.getmetrics()
    family, style = font.getname()
    asc_em, desc_em = ascent / METRIC_SIZE, descent / METRIC_SIZE
    return FontMetrics(
        path=str(path), family=family or Path(path).stem, style=style or "Regular",
        size=float(size), advance_em=adv / METRIC_SIZE, ascent_em=asc_em, descent_em=desc_em,
        line_height_em=line_height if line_height is not None else asc_em + desc_em,
    )


def render_glyph(font: ImageFont.FreeTypeFont, ch: str, metrics: FontMetrics,
                 px: float) -> np.ndarray:
    """Render one glyph into a cell-sized grayscale bitmap (0..1 ink)."""
    w = max(1, round(metrics.advance_em * px))
    h = max(1, round(metrics.line_height_em * px))
    img = Image.new("L", (w, h), 0)
    ImageDraw.Draw(img).text((0, metrics.baseline_em * px), ch, fill=255, font=font, anchor="ls")
    return np.asarray(img, dtype=np.float32) / 255.0


def calibrate(path: str | Path, glyph_text: str, size: float, line_height: float | None,
              pattern_shape: tuple[int, int], allow_proportional: bool = False) -> GlyphSet:
    """Measure each glyph's real ink coverage and shape; return them sorted lightest first."""
    glyphs = parse_glyphs(glyph_text)
    metrics = measure_font(path, size, line_height, glyphs, allow_proportional)
    px = size * CALIBRATION_SCALE
    font = load_font(path, px)
    missing = render_glyph(font, _MISSING_PROBE, metrics, px)
    oy, ox = pattern_shape

    rows = []
    for ch in glyphs:
        bitmap = render_glyph(font, ch, metrics, px)
        if ch != " ":
            if bitmap.max() == 0:
                raise EncodeError(f"glyph {ch!r} renders blank in {metrics.family}")
            if missing.max() > 0 and np.array_equal(bitmap, missing):
                raise EncodeError(f"font {metrics.family} has no glyph for {ch!r} "
                                  f"(U+{ord(ch):04X})")
        small = Image.fromarray((bitmap * 255).astype(np.uint8)).resize((ox, oy), Image.BOX)
        rows.append((ch, float(bitmap.mean()), np.asarray(small, np.float32).ravel() / 255.0))

    rows.sort(key=lambda r: (r[0] != " ", r[1], ord(r[0])))
    chars = [r[0] for r in rows]
    raw = np.array([r[1] for r in rows], dtype=np.float32)
    span = float(raw.max() - raw[0])
    if span <= 0:
        raise EncodeError("all glyphs have identical coverage; choose a more varied glyph set")
    coverage = (raw - raw[0]) / span
    patterns = np.stack([r[2] for r in rows])
    patterns -= patterns.mean(axis=1, keepdims=True)
    norms = np.linalg.norm(patterns, axis=1, keepdims=True)
    patterns = np.where(norms > 1e-6, patterns / np.maximum(norms, 1e-6), 0.0)
    return GlyphSet(chars=chars, coverage=coverage.astype(np.float32), raw_coverage=raw,
                    patterns=patterns.astype(np.float32), metrics=metrics)


def grid_size(width: int, height: int, columns: int, metrics: FontMetrics,
              min_rows: int = 20, max_rows: int = 240) -> tuple[int, int, str | None]:
    """rows = round(columns * height / width * cell_width / cell_height), clamped."""
    rows = round(columns * height / width * metrics.cell_aspect)
    warning = None
    if rows < min_rows or rows > max_rows:
        clamped = min(max(rows, min_rows), max_rows)
        warning = (f"computed {rows} rows for {columns} columns; clamped to {clamped} "
                   "(the image will be letterboxed/stretched — adjust --columns instead)")
        rows = clamped
    return columns, rows, warning


def render_grid_image(grid: np.ndarray, glyphs: GlyphSet, foreground: str, background: str,
                      size: float = 12.0) -> Image.Image:
    """Rasterise a glyph grid with the calibration font (preview/debug screenshots)."""
    m = glyphs.metrics
    font = load_font(m.path, size)
    cw, ch = m.advance_em * size, m.line_height_em * size
    rows, cols = grid.shape
    img = Image.new("RGB", (round(cols * cw), round(rows * ch)), background)
    draw = ImageDraw.Draw(img)
    for r in range(rows):
        y = r * ch + m.baseline_em * size
        for c in range(cols):
            g = glyphs.chars[grid[r, c]]
            if g != " ":
                draw.text((round(c * cw), y), g, fill=foreground, font=font, anchor="ls")
    return img
