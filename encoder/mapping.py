"""Luminance processing and image-to-glyph mapping.

Pipeline per frame:

1. sRGB pixels -> linear-light relative luminance (Rec. 709 weights).
2. Area-average linear light over each character cell (physically correct
   mixing), then re-encode with the sRGB transfer curve to get a perceptual
   *tone* in 0..1.
3. Tone curve: auto-levels, contrast, brightness, gamma. Polarity follows the
   theme: on a dark background bright pixels need dense glyphs (ink = tone);
   on a light background dark pixels do (ink = 1 - tone). ``invert`` flips it.
4. Pick the glyph whose calibrated coverage is nearest the ink target, plus a
   static seeded per-cell offset (``variation``) and optional ordered dither so
   flat regions use a mix of similar-coverage glyphs instead of one repeated
   character. The offset is fixed per cell, so it adds texture, not flicker.
5. Optional ``detail`` weighting adds a shape term so glyphs whose strokes
   follow local edges win: ``detail * contrast * (1 - cos)``, where
   ``contrast`` is the RMS of the cell's zero-mean sub-cell pattern and
   ``cos`` its cosine similarity with the glyph's pattern. Flat cells get no
   shape preference; scale differences between glyph strokes and image
   values do not matter.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .glyphs import GlyphSet

_SRGB = np.arange(256, dtype=np.float64) / 255.0
SRGB_TO_LINEAR = np.where(_SRGB <= 0.04045, _SRGB / 12.92,
                          ((_SRGB + 0.055) / 1.055) ** 2.4).astype(np.float32)
LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

BAYER4 = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]],
                   dtype=np.float32) + 0.5) / 16.0 - 0.5


def linear_luminance(rgb: np.ndarray) -> np.ndarray:
    """(H, W, 3) uint8 sRGB -> (H, W) float32 linear relative luminance."""
    lin = SRGB_TO_LINEAR[rgb]
    return lin @ LUMA


def srgb_encode(linear: np.ndarray) -> np.ndarray:
    linear = np.clip(linear, 0.0, 1.0)
    return np.where(linear <= 0.0031308, linear * 12.92,
                    1.055 * np.power(linear, 1 / 2.4) - 0.055).astype(np.float32)


def hex_luminance(color: str) -> float:
    rgb = np.array([int(color[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.uint8)
    return float(SRGB_TO_LINEAR[rgb] @ LUMA)


def ink_is_light(foreground: str, background: str) -> bool:
    return hex_luminance(foreground) > hex_luminance(background)


@dataclass(frozen=True)
class ToneCurve:
    low: float = 0.0
    high: float = 1.0
    brightness: float = 0.0
    contrast: float = 1.0
    gamma: float = 1.0
    ink_light: bool = True
    invert: bool = False

    def apply(self, tone: np.ndarray) -> np.ndarray:
        """Perceptual tone (0..1) -> ink target (0 = background, 1 = densest glyph)."""
        span = max(self.high - self.low, 1e-6)
        t = (tone - self.low) / span
        t = (t - 0.5) * self.contrast + 0.5 + self.brightness
        t = np.clip(t, 0.0, 1.0)
        if self.gamma != 1.0:
            t = np.power(t, self.gamma)
        if self.ink_light == self.invert:
            t = 1.0 - t
        return t.astype(np.float32)


@dataclass
class CellImage:
    target: np.ndarray  # (rows, cols) ink target
    pattern: np.ndarray | None  # (rows, cols, oy*ox) zero-mean ink pattern, or None


def analyze(rgb: np.ndarray, rows: int, cols: int, curve: ToneCurve,
            with_pattern: bool) -> CellImage:
    """Turn one sampled frame of size (rows*oy, cols*ox) into per-cell ink targets."""
    h, w = rgb.shape[:2]
    oy, ox = h // rows, w // cols
    if oy * rows != h or ox * cols != w:
        raise ValueError(f"frame {w}x{h} is not a multiple of grid {cols}x{rows}")
    lin = linear_luminance(rgb).reshape(rows, oy, cols, ox)
    target = curve.apply(srgb_encode(lin.mean(axis=(1, 3))))
    pattern = None
    if with_pattern:
        sub = curve.apply(srgb_encode(lin)).transpose(0, 2, 1, 3).reshape(rows, cols, oy * ox)
        pattern = sub - sub.mean(axis=2, keepdims=True)
    return CellImage(target, pattern)


def measure_tone_levels(frames, low_pct: float, high_pct: float) -> tuple[float, float]:
    """Global tone percentiles over an iterable of RGB frames (used for auto-levels)."""
    hist = np.zeros(1024, dtype=np.int64)
    seen = False
    for rgb in frames:
        tone = srgb_encode(linear_luminance(rgb))
        hist += np.histogram(tone, bins=1024, range=(0.0, 1.0))[0]
        seen = True
    if not seen or hist.sum() == 0:
        return 0.0, 1.0
    cdf = np.cumsum(hist) / hist.sum()
    low = float(np.searchsorted(cdf, low_pct / 100.0)) / 1024
    high = float(np.searchsorted(cdf, high_pct / 100.0) + 1) / 1024
    if high - low < 0.05:  # nearly flat footage: leave levels alone
        return 0.0, 1.0
    return round(low, 4), round(min(high, 1.0), 4)


class GlyphMapper:
    """Map ink targets to glyph-table indices, deterministically."""

    def __init__(self, glyphs: GlyphSet, rows: int, cols: int, *, detail: float = 0.0,
                 dither: float = 0.0, variation: float = 0.0, seed: int = 1):
        self.glyphs = glyphs
        self.rows, self.cols = rows, cols
        self.detail = float(detail)
        self.coverage = glyphs.coverage.astype(np.float32)
        self.midpoints = (self.coverage[1:] + self.coverage[:-1]) / 2
        step = 1.0 / max(len(glyphs) - 1, 1)
        rng = np.random.default_rng(seed)
        offset = (rng.random((rows, cols), dtype=np.float32) - 0.5) * variation * step
        if dither:
            offset += np.tile(BAYER4, (rows // 4 + 1, cols // 4 + 1))[:rows, :cols] * dither * step
        self.offset = offset.ravel().astype(np.float32)
        self.patterns = glyphs.patterns

    def map(self, cells: CellImage, previous: np.ndarray | None = None,
            margin: float = 0.0) -> np.ndarray:
        """Return (rows, cols) uint8 glyph indices.

        With ``previous`` (flat indices from the last frame), a cell keeps its
        old glyph unless the best glyph is better by more than ``margin``.
        """
        t = cells.target.ravel() + self.offset
        n = t.size
        if self.detail > 0 and cells.pattern is not None:
            p = cells.pattern.reshape(n, -1)
            norm = np.linalg.norm(p, axis=1)
            cos = (p @ self.patterns.T) / np.maximum(norm, 1e-6)[:, None]
            contrast = norm / np.sqrt(p.shape[1])
            cost = np.abs(t[:, None] - self.coverage[None, :])
            cost += self.detail * contrast[:, None] * (1.0 - cos)
            best = cost.argmin(axis=1)
            if previous is None or margin <= 0:
                return best.astype(np.uint8).reshape(self.rows, self.cols)
            idx = np.arange(n)
            keep = cost[idx, previous] <= cost[idx, best] + margin
        else:
            best = np.searchsorted(self.midpoints, t)
            if previous is None or margin <= 0:
                return best.astype(np.uint8).reshape(self.rows, self.cols)
            keep = (np.abs(t - self.coverage[previous])
                    <= np.abs(t - self.coverage[best]) + margin)
        return np.where(keep, previous, best).astype(np.uint8).reshape(self.rows, self.cols)


def grid_to_text(grid: np.ndarray, chars: list[str]) -> str:
    table = np.array(chars)
    return "\n".join("".join(row) for row in table[grid])
