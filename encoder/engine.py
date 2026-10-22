"""Deterministic frame generation: source video -> stream of glyph-index grids."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

from .config import EncodeConfig
from .frames import iter_rgb_frames
from .glyphs import GlyphSet, calibrate, grid_size
from .mapping import (CellImage, GlyphMapper, ToneCurve, analyze, ink_is_light,
                      measure_tone_levels)
from .probe import MediaInfo
from .temporal import Stabilizer

LEVELS_FPS = 6  # frame rate of the cheap auto-levels pre-pass
LEVELS_WIDTH = 160


@dataclass
class EngineStats:
    frames: int = 0
    cuts: int = 0


class FrameEngine:
    def __init__(self, cfg: EncodeConfig, info: MediaInfo, glyphs: GlyphSet | None = None):
        self.cfg = cfg
        self.info = info
        self.glyphs = glyphs or calibrate(cfg.font, cfg.glyphs, cfg.font_size, cfg.line_height,
                                          (cfg.oversample_y, cfg.oversample_x),
                                          cfg.allow_proportional_font)
        self.columns, self.rows, self.grid_warning = grid_size(
            info.width, info.height, cfg.columns, self.glyphs.metrics, cfg.min_rows, cfg.max_rows)
        self.levels = (0.0, 1.0)
        self.stats = EngineStats()

    @property
    def sample_size(self) -> tuple[int, int]:
        return self.columns * self.cfg.oversample_x, self.rows * self.cfg.oversample_y

    def measure_levels(self) -> tuple[float, float]:
        """Cheap pre-pass over a downscaled, low-fps decode for global auto-levels."""
        if self.cfg.auto_levels:
            w = min(LEVELS_WIDTH, self.info.width) // 2 * 2
            h = max(2, round(w * self.info.height / self.info.width) // 2 * 2)
            frames = iter_rgb_frames(self.info, min(self.cfg.fps, LEVELS_FPS), w, h)
            self.levels = measure_tone_levels(frames, self.cfg.levels_low_percentile,
                                              self.cfg.levels_high_percentile)
        return self.levels

    def tone_curve(self) -> ToneCurve:
        c = self.cfg
        return ToneCurve(low=self.levels[0], high=self.levels[1], brightness=c.brightness,
                         contrast=c.contrast, gamma=c.gamma,
                         ink_light=ink_is_light(c.foreground, c.background), invert=c.invert)

    def mapper(self) -> GlyphMapper:
        c = self.cfg
        return GlyphMapper(self.glyphs, self.rows, self.columns, detail=c.detail,
                           dither=c.dither, variation=c.variation, seed=c.seed)

    def cells(self, rgb: np.ndarray, curve: ToneCurve) -> CellImage:
        return analyze(rgb, self.rows, self.columns, curve, with_pattern=self.cfg.detail > 0)

    def grids(self, max_frames: int | None = None, start: float = 0.0) -> Iterator[np.ndarray]:
        """Yield (rows, columns) uint8 glyph-index grids for every output frame."""
        c = self.cfg
        curve = self.tone_curve()
        mapper = self.mapper()
        stab = Stabilizer(c.stability, c.stabilization, c.cut_threshold)
        boundaries = {round(t * c.fps) for t in c.scene_cuts}
        w, h = self.sample_size
        limit = c.max_frames if max_frames is None else min(max_frames, c.max_frames)
        for i, rgb in enumerate(iter_rgb_frames(self.info, c.fps, w, h, limit, start)):
            cells = self.cells(rgb, curve)
            cells.target, _ = stab.filter(cells.target, boundary=i > 0 and i in boundaries)
            previous, margin = stab.hysteresis()
            grid = mapper.map(cells, previous, margin)
            stab.commit(grid)
            self.stats.frames = i + 1
            self.stats.cuts = stab.cuts
            yield grid
