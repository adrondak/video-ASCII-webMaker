"""Deterministic frame generation: source video -> stream of glyph-index grids."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

from .config import EncodeConfig
from .errors import EncodeError
from .frames import iter_rgb_frames
from .glyphs import GlyphSet, calibrate, grid_size
from .mapping import (SRGB_TO_LINEAR, CellImage, GlyphMapper, ToneCurve, analyze,
                      ink_is_light, measure_tone_levels, srgb_encode)
from .probe import MediaInfo
from .temporal import Stabilizer

LEVELS_FPS = 6  # frame rate of the cheap auto-levels pre-pass
LEVELS_WIDTH = 160
MAX_BUFFERED_CELLS = 1 << 30  # grids held in memory for the seamless-loop splice


@dataclass
class EngineStats:
    frames: int = 0
    cuts: int = 0
    crossfade_frames: int = 0
    loop_splice: int = -1


def dissolve(a: np.ndarray, b: np.ndarray, w: float) -> np.ndarray:
    """Mix two sRGB uint8 frames in linear light: ``w * a + (1 - w) * b``."""
    lin = w * SRGB_TO_LINEAR[a] + (1.0 - w) * SRGB_TO_LINEAR[b]
    return np.round(srgb_encode(lin) * 255.0).astype(np.uint8)


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
        self.on_frame = None  # optional progress callback(frames_done)

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

    def source_frames(self, limit: int, start: float = 0.0) -> Iterator[np.ndarray]:
        """Sampled RGB frames, with the optional seamless-loop crossfade applied.

        With ``loop_crossfade`` = K frames, a first pass keeps the last K frames;
        the film is then shortened by K and its first K frames dissolve from
        that tail into the opening, so frame L-1 flows straight into frame 0.
        """
        c = self.cfg
        w, h = self.sample_size
        k = round(c.loop_crossfade * c.fps)
        if k == 0 or start > 0:
            yield from iter_rgb_frames(self.info, c.fps, w, h, limit, start)
            return
        tail: deque[np.ndarray] = deque(maxlen=k)
        n = 0
        for rgb in iter_rgb_frames(self.info, c.fps, w, h, limit):
            tail.append(rgb)
            n += 1
        if n < 3 * k:
            raise EncodeError(f"loop_crossfade of {k} frames needs a film of at least {3 * k} "
                              f"frames (this one has {n})")
        self.stats.crossfade_frames = k
        tail_frames = list(tail)
        for i, rgb in enumerate(iter_rgb_frames(self.info, c.fps, w, h, n - k)):
            yield dissolve(rgb, tail_frames[i], (i + 0.5) / k) if i < k else rgb

    def _map(self, frames, stab: Stabilizer, curve: ToneCurve, mapper: GlyphMapper,
             boundaries: set[int], record: bool = True) -> Iterator[np.ndarray]:
        for i, rgb in enumerate(frames):
            cells = self.cells(rgb, curve)
            cells.target, _ = stab.filter(cells.target, boundary=i > 0 and i in boundaries)
            previous, margin = stab.hysteresis()
            grid = mapper.map(cells, previous, margin)
            stab.commit(grid)
            if record:
                self.stats.frames = i + 1
                self.stats.cuts = stab.cuts
                if self.on_frame:
                    self.on_frame(i + 1)
            yield grid

    def grids(self, max_frames: int | None = None, start: float = 0.0) -> Iterator[np.ndarray]:
        """Yield (rows, columns) uint8 glyph-index grids for every output frame."""
        c = self.cfg
        curve = self.tone_curve()
        mapper = self.mapper()
        stab = Stabilizer(c.stability, c.stabilization, c.cut_threshold)
        boundaries = {round(t * c.fps) for t in c.scene_cuts}
        limit = c.max_frames if max_frames is None else min(max_frames, c.max_frames)
        frames = self.source_frames(limit, start)
        if not (c.loop_crossfade > 0 and start == 0 and stab.enabled):
            yield from self._map(frames, stab, curve, mapper, boundaries)
            return
        yield from self._seamless(frames, stab, curve, mapper, boundaries)

    def _seamless(self, frames, stab, curve, mapper, boundaries) -> Iterator[np.ndarray]:
        """Make the loop point continuous for the stabiliser too.

        Hysteresis holds glyphs, so a film encoded from a fresh state starts with
        different glyphs than its stabilised last frame shows — a one-frame
        shimmer at every loop. After the main pass, the stabiliser carries on from
        the end state through the opening second; that run replaces the opening
        up to the frame where it agrees best with the main pass.
        """
        head: list[np.ndarray] = []
        span = max(2, round(self.cfg.fps))

        def capture(it):
            for i, rgb in enumerate(it):
                if i < span:
                    head.append(rgb)
                yield rgb

        main: list[np.ndarray] = []
        for grid in self._map(capture(frames), stab, curve, mapper, boundaries):
            main.append(grid)
            if len(main) * grid.size > MAX_BUFFERED_CELLS:
                raise EncodeError("film too large to buffer for loop_crossfade; disable it or "
                                  "lower --columns/--fps")
        span = min(span, len(main) // 3)
        wrapped = list(self._map(iter(head[:span]), stab, curve, mapper, boundaries, record=False))
        diffs = [int(np.count_nonzero(wrapped[j] != main[j])) for j in range(span)]
        splice = min(range(span // 2, span), key=lambda j: (diffs[j], -j))
        self.stats.loop_splice = splice
        yield from wrapped[:splice + 1]
        yield from main[splice + 1:]
