import numpy as np
import pytest

from encoder.config import DEFAULT_FONT, DEFAULT_GLYPHS
from encoder.errors import EncodeError
from encoder.glyphs import calibrate, grid_size, parse_glyphs, render_glyph, load_font
from encoder.mapping import (CellImage, GlyphMapper, ToneCurve, analyze, ink_is_light,
                             linear_luminance, measure_tone_levels, srgb_encode)


@pytest.fixture(scope="module")
def glyphs():
    return calibrate(DEFAULT_FONT, DEFAULT_GLYPHS, 20, None, (8, 4))


def test_calibration_sorts_by_measured_ink(glyphs):
    assert glyphs.chars[0] == " "
    assert glyphs.coverage[0] == 0.0 and glyphs.coverage[-1] == pytest.approx(1.0)
    assert np.all(np.diff(glyphs.raw_coverage) >= 0)
    font = load_font(DEFAULT_FONT, 60)
    measured = [render_glyph(font, ch, glyphs.metrics, 60).mean() for ch in glyphs.chars]
    assert measured == sorted(measured)
    # literal order is NOT ink order: '.' is lighter than ',' is not guaranteed, but '@'/'M'
    # being denser than ':' always is.
    assert glyphs.chars.index("@") > glyphs.chars.index(":")
    assert set(glyphs.chars) == set(DEFAULT_GLYPHS)


def test_metrics_are_fixed_pitch(glyphs):
    m = glyphs.metrics
    assert m.family == "DejaVu Sans Mono"
    assert m.advance_em == pytest.approx(0.602, abs=0.002)
    assert 0.4 < m.cell_aspect < 0.6


def test_parse_glyphs_validation():
    assert parse_glyphs("ab") == [" ", "a", "b"]
    assert parse_glyphs("aab ") == ["a", "b", " "]
    for bad in ["á", "\t", "a​", "漢"]:
        with pytest.raises(EncodeError):
            parse_glyphs(bad)
    with pytest.raises(EncodeError):
        parse_glyphs(" ")


def test_missing_glyph_rejected():
    with pytest.raises(EncodeError, match="no glyph"):
        calibrate(DEFAULT_FONT, " .\u0f40", 20, None, (8, 4))


def test_proportional_font_rejected(tmp_path):
    import shutil
    from pathlib import Path
    candidates = [Path("/System/Library/Fonts/Helvetica.ttc"),
                  Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    font = next((p for p in candidates if p.exists()), None)
    if font is None:
        pytest.skip("no proportional system font found")
    with pytest.raises(EncodeError, match="fixed-pitch"):
        calibrate(font, DEFAULT_GLYPHS, 20, None, (8, 4))


@pytest.mark.parametrize("w,h,cols", [(1920, 1080, 160), (1080, 1920, 80), (640, 480, 100)])
def test_grid_aspect_formula(glyphs, w, h, cols):
    c, rows, warning = grid_size(w, h, cols, glyphs.metrics, 1, 1000)
    expected = round(cols * h / w * glyphs.metrics.cell_width / glyphs.metrics.cell_height)
    assert (c, rows, warning) == (cols, expected, None)
    # The rendered grid's physical aspect matches the source within one row.
    assert abs(cols * glyphs.metrics.cell_width / (rows * glyphs.metrics.cell_height) - w / h) \
        < w / h / rows * 1.01


def test_grid_clamps_with_warning(glyphs):
    _, rows, warning = grid_size(1080, 1920, 320, glyphs.metrics, 20, 240)
    assert rows == 240 and "clamped" in warning


def _solid(value, rows=4, cols=6, oy=8, ox=4):
    return np.full((rows * oy, cols * ox, 3), value, dtype=np.uint8)


def test_black_white_and_polarity(glyphs):
    mapper = GlyphMapper(glyphs, 4, 6)
    dark_bg = ToneCurve(ink_light=True)
    black = mapper.map(analyze(_solid(0), 4, 6, dark_bg, False))
    white = mapper.map(analyze(_solid(255), 4, 6, dark_bg, False))
    assert np.all(black == 0) and np.all(white == len(glyphs) - 1)
    light_bg = ToneCurve(ink_light=False)
    assert np.all(mapper.map(analyze(_solid(255), 4, 6, light_bg, False)) == 0)
    inverted = ToneCurve(ink_light=True, invert=True)
    assert np.all(mapper.map(analyze(_solid(0), 4, 6, inverted, False)) == len(glyphs) - 1)


def test_gradient_is_monotonic(glyphs):
    cols = 64
    ramp = np.linspace(0, 255, cols * 4).astype(np.uint8)
    rgb = np.repeat(np.tile(ramp, (8, 1))[:, :, None], 3, axis=2)
    grid = GlyphMapper(glyphs, 1, cols).map(analyze(rgb, 1, cols, ToneCurve(), False))
    cov = glyphs.coverage[grid[0]]
    assert np.all(np.diff(cov) >= -1e-6)
    assert grid[0, 0] == 0 and cov[-1] > 0.95


@pytest.mark.parametrize("kw", [dict(contrast=5.0), dict(contrast=0.1), dict(gamma=0.1),
                                dict(gamma=5.0), dict(brightness=1.0), dict(brightness=-1.0)])
def test_tone_extremes_stay_in_range(kw):
    t = ToneCurve(**kw).apply(np.linspace(0, 1, 101, dtype=np.float32))
    assert t.min() >= 0 and t.max() <= 1 and np.all(np.diff(t) >= -1e-6)


def test_area_average_is_linear_light():
    # Half black / half white sub-pixels average to 50% linear light, i.e. ~0.735 sRGB tone.
    rgb = np.zeros((8, 4, 3), np.uint8)
    rgb[:, :2] = 255
    cells = analyze(rgb, 1, 1, ToneCurve(), False)
    assert cells.target[0, 0] == pytest.approx(float(srgb_encode(np.float32(0.5))), abs=1e-3)


def test_variation_mixes_glyphs_deterministically(glyphs):
    rows, cols = 20, 40
    flat = CellImage(np.full((rows, cols), 0.71, np.float32), None)  # 3/h/5/X/S cluster
    plain = GlyphMapper(glyphs, rows, cols).map(flat)
    varied = GlyphMapper(glyphs, rows, cols, variation=1.5, seed=7).map(flat)
    again = GlyphMapper(glyphs, rows, cols, variation=1.5, seed=7).map(flat)
    assert len(np.unique(plain)) == 1
    assert len(np.unique(varied)) > 1
    assert np.array_equal(varied, again)
    # Variation keeps the average density close to the target.
    assert abs(glyphs.coverage[varied].mean() - 0.71) < 0.05


def test_detail_prefers_shape_matching_glyph():
    g = calibrate(DEFAULT_FONT, " -|", 20, None, (8, 4))
    # A vertical bright stripe in the middle of a cell should pick '|' over '-'.
    rgb = np.zeros((8, 4, 3), np.uint8)
    rgb[:, 1:3] = 200
    curve = ToneCurve()
    mapper = GlyphMapper(g, 1, 1, detail=2.0)
    assert g.chars[mapper.map(analyze(rgb, 1, 1, curve, True))[0, 0]] == "|"
    rgb = np.zeros((8, 4, 3), np.uint8)
    rgb[3:5, :] = 255
    assert g.chars[mapper.map(analyze(rgb, 1, 1, curve, True))[0, 0]] == "-"


def test_auto_levels():
    frames = [np.full((4, 4, 3), v, np.uint8) for v in (60, 120, 180)]
    low, high = measure_tone_levels(frames, 0.5, 99.5)
    assert 0.2 < low < 0.25 and 0.7 < high < 0.72
    assert measure_tone_levels([np.full((4, 4, 3), 90, np.uint8)], 0.5, 99.5) == (0.0, 1.0)


def test_theme_polarity():
    assert ink_is_light("#eeeeee", "#101010")
    assert not ink_is_light("#111111", "#fafafa")


def test_linear_luminance_endpoints():
    lum = linear_luminance(np.array([[[0, 0, 0], [255, 255, 255], [255, 0, 0]]], np.uint8))
    assert lum[0, 0] == 0 and lum[0, 1] == pytest.approx(1.0) and lum[0, 2] == pytest.approx(0.2126)
