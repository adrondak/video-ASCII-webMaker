import json
from fractions import Fraction

import pytest

from encoder.config import build_config
from encoder.errors import ConfigError, EncodeError
from encoder.frames import iter_rgb_frames
from encoder.probe import probe


def test_defaults_are_valid():
    cfg, warnings = build_config()
    assert cfg.fps == 24 and cfg.columns == 160 and cfg.stability == 0.25
    assert warnings == []


def test_cli_overrides_config_file(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"fps": 12, "columns": 100, "_comment": "ignored"}))
    cfg, _ = build_config(path, {"columns": 80, "fps": None})
    assert cfg.fps == 12 and cfg.columns == 80


@pytest.mark.parametrize("bad", [
    {"fps": 0}, {"fps": 61}, {"columns": 39}, {"columns": 321}, {"stability": 1.5},
    {"foreground": "white"}, {"autoplay": "loud"}, {"fps": 2.5}, {"loop": "yes"},
])
def test_invalid_values_rejected(bad):
    with pytest.raises(ConfigError):
        build_config(None, bad)


def test_unknown_config_key_rejected(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"colums": 100}))
    with pytest.raises(ConfigError, match="unknown option"):
        build_config(path)


def test_probe_landscape(fixtures_dir):
    info = probe(fixtures_dir / "landscape.mp4")
    assert (info.width, info.height) == (640, 360)
    assert info.frame_rate == Fraction(30)
    assert info.has_audio
    assert 4.9 < info.duration < 5.2


def test_probe_rotation_swaps_display_size(fixtures_dir):
    info = probe(fixtures_dir / "rotated.mp4")
    assert info.rotation in (90, 270)
    assert (info.width, info.height) == (360, 640)


def test_probe_silent(fixtures_dir):
    assert not probe(fixtures_dir / "silent.mp4").has_audio


def test_probe_rejects_non_video(tmp_path):
    bogus = tmp_path / "notes.mp4"
    bogus.write_text("this is not a video")
    with pytest.raises(EncodeError):
        probe(bogus)
    with pytest.raises(EncodeError, match="not found"):
        probe(tmp_path / "missing.mp4")


def test_decode_resamples_to_constant_fps(fixtures_dir):
    info = probe(fixtures_dir / "landscape.mp4")
    frames = list(iter_rgb_frames(info, 24, 64, 36))
    assert len(frames) == 120  # 5 s at 24 fps from a 30 fps source
    assert frames[0].shape == (36, 64, 3)


def test_decode_respects_rotation(fixtures_dir):
    info = probe(fixtures_dir / "rotated.mp4")
    frame = next(iter_rgb_frames(info, 24, 36, 64))
    assert frame.shape == (64, 36, 3)
