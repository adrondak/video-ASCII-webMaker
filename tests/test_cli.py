"""End-to-end tests: encode synthetic fixtures through the real CLI."""

import json
import subprocess
from pathlib import Path

import pytest

from encoder.cli import main
from encoder.container import AscfFile


def _encode(src, out, *extra):
    return main(["encode", str(src), "--output", str(out), *extra])


def _manifest(out):
    return json.loads((Path(out) / "manifest.json").read_text())


def _ffprobe_duration(path, stream):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries",
                        "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


@pytest.fixture(scope="module")
def landscape_out(fixtures_dir, tmp_path_factory):
    out = tmp_path_factory.mktemp("enc") / "landscape"
    assert _encode(fixtures_dir / "landscape.mp4", out) == 0
    return out


def test_default_encode_package(landscape_out):
    files = {p.name for p in landscape_out.iterdir()}
    assert {"index.html", "player.js", "decoder.js", "renderer.js", "player.css", ".htaccess",
            "film.ascf", "manifest.json", "font.woff2", "FONT-LICENSE.txt"} <= files
    assert not any(n.endswith((".mp4", ".mov")) for n in files)  # never ship source media
    m = _manifest(landscape_out)
    assert m["schemaVersion"] == 1 and m["frameCount"] == 120
    assert m["durationSeconds"] == pytest.approx(5.0)
    assert m["audio"] is None  # audio is opt-in
    assert m["fps"] == {"numerator": 24, "denominator": 1}
    assert m["loop"] is True and m["autoplay"] == "muted"
    for value in (m["animation"], m["font"]["file"]):
        assert "/" not in value and not value.startswith(".")  # relative, same directory


def test_inspect_matches_manifest(landscape_out, capsys):
    assert main(["inspect", str(landscape_out / "film.ascf")]) == 0
    out = capsys.readouterr().out
    assert "120 at 24/1 fps = 5.000 s" in out and "OK" in out
    f = AscfFile.open(landscape_out / "film.ascf")
    m = _manifest(landscape_out)
    assert (f.header.columns, f.header.rows) == (m["columns"], m["rows"])
    assert f.header.duration_us == round(m["durationSeconds"] * 1e6)


def test_hard_cut_is_not_stabilised_across(landscape_out):
    # The fixture cuts from a gradient to a test pattern at 2.5 s (frame 60 at 24 fps).
    f = AscfFile.open(landscape_out / "film.ascf")
    before, after = f.frame(59), f.frame(60)
    assert (before != after).mean() > 0.3


def test_inspect_rejects_corrupt_file(tmp_path, landscape_out, capsys):
    bad = tmp_path / "bad.ascf"
    data = bytearray((landscape_out / "film.ascf").read_bytes())
    data[0] = 0
    bad.write_bytes(bytes(data))
    assert main(["inspect", str(bad)]) == 1
    assert "INVALID" in capsys.readouterr().err


def test_deterministic_animation(fixtures_dir, tmp_path, landscape_out):
    out = tmp_path / "again"
    assert _encode(fixtures_dir / "landscape.mp4", out) == 0
    assert (out / "film.ascf").read_bytes() == (landscape_out / "film.ascf").read_bytes()


def test_audio_opt_in(fixtures_dir, tmp_path):
    out = tmp_path / "with-audio"
    assert _encode(fixtures_dir / "landscape.mp4", out, "--audio") == 0
    m = _manifest(out)
    assert m["audio"] == "audio.m4a"
    assert _ffprobe_duration(out / "audio.m4a", "a:0") == pytest.approx(m["durationSeconds"], abs=0.05)


def test_silent_source(fixtures_dir, tmp_path):
    out = tmp_path / "silent"
    assert _encode(fixtures_dir / "silent.mp4", out, "--audio") == 0
    m = _manifest(out)
    assert m["audio"] is None and m["frameCount"] == 72


@pytest.mark.parametrize("name", ["portrait.mp4", "rotated.mp4"])
def test_portrait_geometry(fixtures_dir, tmp_path, name):
    out = tmp_path / name
    assert _encode(fixtures_dir / name, out, "--columns", "60") == 0
    m = _manifest(out)
    aspect = m["columns"] * m["font"]["cellWidth"] / (m["rows"] * m["font"]["cellHeight"])
    assert aspect == pytest.approx(360 / 640, rel=0.04)


def test_refuses_to_overwrite_without_force(fixtures_dir, tmp_path, capsys):
    out = tmp_path / "exists"
    out.mkdir()
    (out / "keep.txt").write_text("x")
    assert _encode(fixtures_dir / "silent.mp4", out) == 2
    assert "--force" in capsys.readouterr().err
    assert (out / "keep.txt").exists()
    assert _encode(fixtures_dir / "silent.mp4", out, "--force") == 0
    assert not (out / "keep.txt").exists() and (out / "film.ascf").exists()
    assert not list(tmp_path.glob(".*staging*")) and not list(tmp_path.glob(".*old*"))


def test_unsupported_input_fails_cleanly(tmp_path, capsys):
    bogus = tmp_path / "bogus.mov"
    bogus.write_bytes(b"\0" * 1000)
    assert _encode(bogus, tmp_path / "out") == 2
    assert "error:" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_output_must_not_contain_source(fixtures_dir, tmp_path, capsys):
    src = tmp_path / "clip.mp4"
    src.write_bytes((fixtures_dir / "silent.mp4").read_bytes())
    assert _encode(src, tmp_path, "--force") == 2
    assert src.exists()


def test_bad_option_value(fixtures_dir, tmp_path, capsys):
    assert _encode(fixtures_dir / "silent.mp4", tmp_path / "o", "--columns", "999") == 2
    assert "columns" in capsys.readouterr().err


def test_preview_text(fixtures_dir, capsys):
    assert main(["preview", str(fixtures_dir / "landscape.mp4"), "--time", "1",
                 "--columns", "80"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines[0]) == 80 and len(lines) > 10


def test_loop_crossfade_makes_seam_continuous(fixtures_dir, tmp_path, landscape_out):
    out = tmp_path / "xfade"
    assert _encode(fixtures_dir / "landscape.mp4", out, "--loop-crossfade", "0.5") == 0
    m = _manifest(out)
    assert m["frameCount"] == 108 and m["encoding"]["loopCrossfadeFrames"] == 12
    plain = AscfFile.open(landscape_out / "film.ascf")
    faded = AscfFile.open(out / "film.ascf")
    jump_plain = (plain.frame(119) != plain.frame(0)).mean()
    jump_faded = (faded.frame(107) != faded.frame(0)).mean()
    assert jump_faded < jump_plain / 3
    # Past the crossfade the film is untouched.
    assert (faded.frame(60) == plain.frame(60)).mean() > 0.95


def test_crossfade_with_audio_rejected(fixtures_dir, tmp_path, capsys):
    assert _encode(fixtures_dir / "landscape.mp4", tmp_path / "o", "--audio",
                   "--loop-crossfade", "0.5") == 2
    assert "loop_crossfade" in capsys.readouterr().err
