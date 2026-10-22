import struct
import zlib

import numpy as np
import pytest

from encoder.container import (HEADER_SIZE, INDEX_ENTRY_SIZE, AscfFile, AscfWriter, Limits,
                               timestamp_us)
from encoder.errors import AscfError

GLYPHS = [" ", ".", ":", "o", "@"]


def _write(path, frames, interval=48, glyphs=GLYPHS, fps=(24, 1)):
    rows, cols = frames[0].shape
    with AscfWriter(path, cols, rows, fps[0], fps[1], glyphs, interval) as w:
        kinds = [w.add_frame(f) for f in frames]
    return kinds, w.stats


def _random_frames(n, rows=6, cols=10, seed=0, change=0.1):
    rng = np.random.default_rng(seed)
    grid = rng.integers(0, len(GLYPHS), (rows, cols), dtype=np.uint8)
    out = []
    for _ in range(n):
        mask = rng.random((rows, cols)) < change
        grid = np.where(mask, rng.integers(0, len(GLYPHS), (rows, cols)), grid).astype(np.uint8)
        out.append(grid.copy())
    return out


def _roundtrip(path, frames):
    f = AscfFile.open(path)
    for i, expected in enumerate(frames):
        assert np.array_equal(f.frame(i), expected), f"frame {i}"
    return f


def test_mixed_roundtrip(tmp_path):
    frames = _random_frames(60)
    kinds, stats = _write(tmp_path / "a.ascf", frames, interval=10)
    assert kinds[0] == 0 and 1 in kinds
    f = _roundtrip(tmp_path / "a.ascf", frames)
    summary = f.validate_all()
    assert summary["keyframes"] + summary["deltas"] == 60
    assert f.header.columns == 10 and f.header.rows == 6 and f.glyphs == GLYPHS
    assert stats.total_bytes == (tmp_path / "a.ascf").stat().st_size


def test_all_keyframes(tmp_path):
    frames = _random_frames(12, change=1.0)
    kinds, _ = _write(tmp_path / "k.ascf", frames, interval=1)
    assert kinds == [0] * 12
    _roundtrip(tmp_path / "k.ascf", frames)


def test_all_delta_and_empty_change(tmp_path):
    base = _random_frames(1, rows=40, cols=60)[0]
    frames = [base] + [base.copy() for _ in range(20)]
    kinds, _ = _write(tmp_path / "d.ascf", frames, interval=100)
    assert kinds == [0] + [1] * 20  # identical frames: empty deltas are tiny
    f = _roundtrip(tmp_path / "d.ascf", frames)
    assert f.payload(5)[0] == 1 and struct.unpack_from("<I", f.payload(5), 1)[0] == 0


def test_keyframe_interval_enforced(tmp_path):
    frames = _random_frames(50, rows=40, cols=60, change=0.01)
    kinds, _ = _write(tmp_path / "i.ascf", frames, interval=8)
    since = 0
    for k in kinds:
        since = 1 if k == 0 else since + 1
        assert since <= 8
    AscfFile.open(tmp_path / "i.ascf").validate_all()


def test_seek_from_keyframe_random_order(tmp_path):
    frames = _random_frames(100)
    _write(tmp_path / "s.ascf", frames, interval=16)
    f = AscfFile.open(tmp_path / "s.ascf")
    for i in np.random.default_rng(3).permutation(100)[:40]:
        assert np.array_equal(f.frame(int(i)), frames[i])
    assert np.array_equal(f.frame(99), frames[99])
    assert np.array_equal(f.frame(0), frames[0])


def test_rational_timestamps_no_drift(tmp_path):
    frames = _random_frames(5)
    _write(tmp_path / "t.ascf", frames, fps=(24000, 1001))
    f = AscfFile.open(tmp_path / "t.ascf")
    assert f.timestamps_exact()
    assert timestamp_us(24000, 24000, 1001) == 1_001_000_000  # exact, no float accumulation
    ts = [timestamp_us(i, 30000, 1001) for i in range(100000)]
    assert all(b > a for a, b in zip(ts, ts[1:]))
    assert ts[-1] == 99999 * 1_000_000 * 1001 // 30000


def test_deterministic_bytes(tmp_path):
    frames = _random_frames(30)
    _write(tmp_path / "1.ascf", frames)
    _write(tmp_path / "2.ascf", frames)
    assert (tmp_path / "1.ascf").read_bytes() == (tmp_path / "2.ascf").read_bytes()


def test_writer_rejects_bad_input(tmp_path):
    with pytest.raises(AscfError):
        AscfWriter(tmp_path / "x.ascf", 4, 4, 24, 0, GLYPHS)
    with pytest.raises(AscfError, match="space"):
        AscfWriter(tmp_path / "x.ascf", 4, 4, 24, 1, [".", " "])
    w = AscfWriter(tmp_path / "x.ascf", 4, 4, 24, 1, GLYPHS)
    with pytest.raises(AscfError, match="glyph index"):
        w.add_frame(np.full((4, 4), 9, np.uint8))
    with pytest.raises(AscfError, match="cells"):
        w.add_frame(np.zeros((3, 4), np.uint8))
    with pytest.raises(AscfError, match="zero frames"):
        w.close()


# ------------------------------------------------------------------ corruption


@pytest.fixture()
def good(tmp_path):
    frames = _random_frames(20)
    _write(tmp_path / "g.ascf", frames, interval=5)
    return bytearray((tmp_path / "g.ascf").read_bytes())


def _expect_error(data, match=None):
    with pytest.raises(AscfError, match=match):
        AscfFile(bytes(data)).validate_all()


def test_bad_magic(good):
    good[0:4] = b"ASCX"
    _expect_error(good, "magic")


def test_bad_major_version(good):
    struct.pack_into("<H", good, 4, 2)
    _expect_error(good, "version")


def test_minor_version_is_tolerated(good):
    struct.pack_into("<H", good, 6, 3)
    AscfFile(bytes(good)).validate_all()


def test_zero_fps_denominator(good):
    struct.pack_into("<I", good, 28, 0)
    _expect_error(good, "non-zero")


def test_truncated_file(good):
    _expect_error(good[:-10], "bytes")
    _expect_error(good[:30], "too small")


def test_bad_index_offset(good):
    struct.pack_into("<Q", good, 48, 10**9)
    _expect_error(good, "index")


def test_payload_offset_out_of_bounds(good):
    ioff = struct.unpack_from("<Q", good, 48)[0]
    struct.pack_into("<Q", good, ioff + 3 * INDEX_ENTRY_SIZE, 10**8)
    _expect_error(good, "out of bounds")


def test_corrupt_zlib(good):
    ioff = struct.unpack_from("<Q", good, 48)[0]
    off, clen = struct.unpack_from("<QI", good, ioff + 2 * INDEX_ENTRY_SIZE)
    good[off + clen // 2] ^= 0xFF
    _expect_error(good)


def test_truncated_zlib_stream(good):
    ioff = struct.unpack_from("<Q", good, 48)[0]
    off, clen = struct.unpack_from("<QI", good, ioff)
    struct.pack_into("<I", good, ioff + 8, clen - 4)
    _expect_error(good)


def test_invalid_glyph_index_in_payload(tmp_path):
    frames = [np.zeros((2, 3), np.uint8)]
    _write(tmp_path / "v.ascf", frames)
    data = bytearray((tmp_path / "v.ascf").read_bytes())
    f = AscfFile(bytes(data))
    off, clen = (int(f.index[0][k]) for k in ("offset", "clen"))
    evil = zlib.compress(bytes([0]) + bytes([0, 1, 2, 3, 4, 200]), 9)
    assert len(evil) <= clen + 8
    rebuilt = data[:off] + evil + data[off + clen:]
    delta = len(evil) - clen
    ioff = struct.unpack_from("<Q", rebuilt, 48)[0] + delta
    struct.pack_into("<Q", rebuilt, 48, ioff)
    struct.pack_into("<Q", rebuilt, 56, len(rebuilt))
    struct.pack_into("<I", rebuilt, ioff + 8, len(evil))
    _expect_error(rebuilt, "glyph index")


def test_invalid_utf8_glyph_table(good):
    good[HEADER_SIZE + 4] = 0xFF
    _expect_error(good, "UTF-8")


def test_glyph_count_mismatch(good):
    struct.pack_into("<I", good, 36, 4)
    _expect_error(good, "glyph")


def test_non_monotonic_timestamps(good):
    ioff = struct.unpack_from("<Q", good, 48)[0]
    struct.pack_into("<Q", good, ioff + 2 * INDEX_ENTRY_SIZE + 16, 0)
    _expect_error(good, "timestamps")


def test_limits_reject_large_grids(good):
    with pytest.raises(AscfError, match="limits"):
        AscfFile(bytes(good), Limits(max_columns=5))
