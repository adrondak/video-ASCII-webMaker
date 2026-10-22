"""Temporal stabilisation: low-pass on cell targets plus per-cell hysteresis.

Mapping every frame independently makes cells near a coverage threshold
flicker between two glyphs. The stabiliser

* smooths each cell's ink target with a light one-pole low-pass, and
* tells the mapper to keep the previous glyph unless the new best glyph beats
  it by more than a margin (hysteresis).

Both scale with ``stability`` (0..1). State is reset at a detected hard cut
(mean absolute target change above ``cut_threshold``) and at explicit scene
boundaries, so nothing is ever smoothed or held across a cut.
"""

from __future__ import annotations

import numpy as np

LOWPASS_PER_STABILITY = 0.5  # weight of the previous target at stability 1.0
MARGIN_PER_STABILITY = 0.10  # hysteresis margin (coverage units) at stability 1.0


class Stabilizer:
    def __init__(self, stability: float = 0.25, enabled: bool = True,
                 cut_threshold: float = 0.22):
        self.enabled = enabled and stability > 0
        self.alpha = LOWPASS_PER_STABILITY * stability if self.enabled else 0.0
        self.margin = MARGIN_PER_STABILITY * stability if self.enabled else 0.0
        self.cut_threshold = cut_threshold
        self.cuts = 0
        self.reset()

    def reset(self) -> None:
        self._raw: np.ndarray | None = None
        self._smoothed: np.ndarray | None = None
        self.previous: np.ndarray | None = None  # flat glyph indices of the last frame

    def is_cut(self, target: np.ndarray) -> bool:
        if self._raw is None:
            return False
        return float(np.mean(np.abs(target - self._raw))) > self.cut_threshold

    def filter(self, target: np.ndarray, boundary: bool = False) -> tuple[np.ndarray, bool]:
        """Return the (possibly smoothed) target and whether a cut reset the state."""
        cut = boundary or self.is_cut(target)
        if cut:
            self.cuts += 1
            self.reset()
        smoothed = target
        if self.enabled and self._smoothed is not None and self.alpha > 0:
            smoothed = (self.alpha * self._smoothed + (1 - self.alpha) * target).astype(np.float32)
        self._raw = target
        self._smoothed = smoothed
        return smoothed, cut

    def hysteresis(self) -> tuple[np.ndarray | None, float]:
        """Previous glyphs and margin to pass to :meth:`GlyphMapper.map`."""
        if not self.enabled:
            return None, 0.0
        return self.previous, self.margin

    def commit(self, grid: np.ndarray) -> None:
        self.previous = grid.ravel().astype(np.intp)
