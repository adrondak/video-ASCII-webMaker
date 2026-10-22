import numpy as np
import pytest

from encoder.config import DEFAULT_FONT, DEFAULT_GLYPHS
from encoder.glyphs import calibrate
from encoder.mapping import CellImage, GlyphMapper
from encoder.temporal import Stabilizer


@pytest.fixture(scope="module")
def mapper():
    g = calibrate(DEFAULT_FONT, DEFAULT_GLYPHS, 20, None, (8, 4))
    return GlyphMapper(g, 10, 10)


def _run(mapper, targets, stab):
    grids = []
    for t in targets:
        target, _ = stab.filter(t)
        prev, margin = stab.hysteresis()
        grid = mapper.map(CellImage(target, None), prev, margin)
        stab.commit(grid)
        grids.append(grid)
    return grids


def _changes(grids):
    return sum(int(np.count_nonzero(a != b)) for a, b in zip(grids, grids[1:]))


def _near_threshold_sequence(mapper, n=40):
    """Targets jittering around the midpoint between two glyphs."""
    mid = float(mapper.midpoints[len(mapper.midpoints) // 2])
    rng = np.random.default_rng(0)
    return [np.full((10, 10), mid, np.float32) + rng.normal(0, 0.004, (10, 10)).astype(np.float32)
            for _ in range(n)]


def test_hysteresis_reduces_flicker(mapper):
    seq = _near_threshold_sequence(mapper)
    raw = _changes(_run(mapper, seq, Stabilizer(0, enabled=False)))
    stable = _changes(_run(mapper, seq, Stabilizer(0.25)))
    assert raw > 500
    assert stable < raw * 0.1


def test_large_changes_still_update(mapper):
    seq = [np.full((10, 10), 0.2, np.float32)] * 3 + [np.full((10, 10), 0.35, np.float32)] * 6
    grids = _run(mapper, seq, Stabilizer(0.25, cut_threshold=0.5))
    assert not np.array_equal(grids[0], grids[-1])
    expected = mapper.map(CellImage(np.full((10, 10), 0.35, np.float32), None))
    assert np.array_equal(grids[-1], expected)


def test_cut_resets_state(mapper):
    stab = Stabilizer(1.0, cut_threshold=0.2)
    dark = np.full((10, 10), 0.1, np.float32)
    bright = np.full((10, 10), 0.9, np.float32)
    _run(mapper, [dark, dark], stab)
    target, cut = stab.filter(bright)
    assert cut and np.array_equal(target, bright)  # no low-pass ghosting across the cut
    assert stab.hysteresis()[0] is None  # no glyphs held across the cut


def test_explicit_boundary_resets(mapper):
    stab = Stabilizer(0.5)
    flat = np.full((10, 10), 0.5, np.float32)
    _run(mapper, [flat], stab)
    _, cut = stab.filter(flat, boundary=True)
    assert cut and stab.cuts == 1


def test_disabled_is_stateless(mapper):
    stab = Stabilizer(0.25, enabled=False)
    t = np.full((10, 10), 0.3, np.float32)
    out, _ = stab.filter(t)
    out2, _ = stab.filter(t * 0)
    assert out2.max() == 0 and stab.hysteresis() == (None, 0.0)
