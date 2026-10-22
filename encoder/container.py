"""ASCF v1: a documented, versioned binary container for glyph animations.

Layout (all integers little-endian)::

    header (64 bytes) | glyph table | frame payloads ... | frame index

Header::

    0  4s   magic "ASCF"            32 u32  keyframe interval
    4  u16  major version (1)       36 u32  glyph count
    6  u16  minor version (0)       40 u64  glyph table offset (64)
    8  u32  header bytes (64)       48 u64  frame index offset
    12 u32  columns                 56 u64  total file bytes
    16 u32  rows
    20 u32  frame count
    24 u32  fps numerator
    28 u32  fps denominator

Glyph table: u32 byte length + UTF-8 JSON array of single-codepoint,
non-combining strings; index 0 is always the space glyph.

Each frame payload is independently zlib-compressed (RFC 1950, zlib framing).
Decompressed, it starts with a type byte:

* ``0x00`` keyframe: ``columns * rows`` u8 glyph indices, row-major.
* ``0x01`` delta: u32 changed-cell count, then ``(u32 cell, u8 glyph)``
  records sorted by cell index, no duplicates, relative to the previous frame.

Frame index: ``frame_count`` entries of 24 bytes: u64 payload offset,
u32 compressed length, u32 uncompressed length, u64 timestamp in µs.

v1 has no checksums: integrity relies on zlib's Adler-32 plus the structural
validation in :class:`AscfFile`.
"""

from __future__ import annotations

import json
import os
import struct
import unicodedata
import zlib
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np

from .errors import AscfError

MAGIC = b"ASCF"
VERSION_MAJOR = 1
VERSION_MINOR = 0
HEADER = struct.Struct("<4sHHIIIIIIIIQQQ")
HEADER_SIZE = 64
INDEX_ENTRY = struct.Struct("<QIIQ")
INDEX_ENTRY_SIZE = 24
KEYFRAME = 0x00
DELTA = 0x01
DELTA_RECORD = np.dtype([("cell", "<u4"), ("glyph", "u1")])
ZLIB_LEVEL = 9

assert HEADER.size == HEADER_SIZE and INDEX_ENTRY.size == INDEX_ENTRY_SIZE


@dataclass(frozen=True)
class Limits:
    max_columns: int = 4096
    max_rows: int = 4096
    max_cells: int = 1 << 22
    max_frames: int = 1_000_000
    max_glyphs: int = 256
    max_glyph_table_bytes: int = 64 * 1024
    max_file_bytes: int = 4 << 30
    max_keyframe_interval: int = 100_000


DEFAULT_LIMITS = Limits()


def timestamp_us(frame: int, fps_num: int, fps_den: int) -> int:
    """Exact integer timestamp of a CFR frame: floor(frame * 1e6 * den / num)."""
    return frame * 1_000_000 * fps_den // fps_num


def validate_glyph_list(glyphs: list, max_glyphs: int = 256) -> list[str]:
    if not isinstance(glyphs, list) or not glyphs:
        raise AscfError("glyph table must be a non-empty JSON array")
    if len(glyphs) > max_glyphs:
        raise AscfError(f"glyph table has {len(glyphs)} entries (max {max_glyphs})")
    for g in glyphs:
        if not isinstance(g, str) or len(g) != 1:
            raise AscfError(f"glyph {g!r} is not a single code point")
        if unicodedata.combining(g) or unicodedata.category(g) in ("Mn", "Mc", "Me", "Cc", "Cs"):
            raise AscfError(f"glyph U+{ord(g):04X} is not a standalone printable glyph")
    if glyphs[0] != " ":
        raise AscfError("glyph index 0 must be the space glyph")
    if len(set(glyphs)) != len(glyphs):
        raise AscfError("glyph table contains duplicates")
    return glyphs


# --------------------------------------------------------------------------- writer


@dataclass
class WriteStats:
    frames: int = 0
    keyframes: int = 0
    deltas: int = 0
    payload_bytes: int = 0
    total_bytes: int = 0


class AscfWriter:
    """Stream frames to an ``.ascf`` file; call :meth:`close` to finalise."""

    def __init__(self, path: str | Path, columns: int, rows: int, fps_num: int, fps_den: int,
                 glyphs: list[str], keyframe_interval: int = 48):
        if fps_num <= 0 or fps_den <= 0:
            raise AscfError("fps numerator and denominator must be positive")
        if keyframe_interval < 1:
            raise AscfError("keyframe interval must be >= 1")
        self.glyphs = validate_glyph_list(list(glyphs))
        self.path = Path(path)
        self.columns, self.rows = columns, rows
        self.cells = columns * rows
        self.fps_num, self.fps_den = fps_num, fps_den
        self.keyframe_interval = keyframe_interval
        self.stats = WriteStats()
        self._index: list[bytes] = []
        self._prev: np.ndarray | None = None
        self._since_key = 0
        self._fh = open(self.path, "wb")
        self._fh.write(b"\0" * HEADER_SIZE)
        table = json.dumps(self.glyphs, ensure_ascii=False, separators=(",", ":")).encode()
        self._fh.write(struct.pack("<I", len(table)) + table)
        self._offset = HEADER_SIZE + 4 + len(table)

    def add_frame(self, grid: np.ndarray) -> int:
        """Append one (rows, columns) uint8 grid. Returns the frame type written."""
        flat = np.ascontiguousarray(grid, dtype=np.uint8).ravel()
        if flat.size != self.cells:
            raise AscfError(f"frame has {flat.size} cells, expected {self.cells}")
        if int(flat.max(initial=0)) >= len(self.glyphs):
            raise AscfError("frame references a glyph index outside the glyph table")
        key_raw = bytes([KEYFRAME]) + flat.tobytes()
        key_z = zlib.compress(key_raw, ZLIB_LEVEL)
        raw, comp, kind = key_raw, key_z, KEYFRAME
        if self._prev is not None and self._since_key < self.keyframe_interval:
            changed = np.flatnonzero(flat != self._prev).astype("<u4")
            records = np.empty(changed.size, dtype=DELTA_RECORD)
            records["cell"] = changed
            records["glyph"] = flat[changed]
            delta_raw = bytes([DELTA]) + struct.pack("<I", changed.size) + records.tobytes()
            delta_z = zlib.compress(delta_raw, ZLIB_LEVEL)
            if len(delta_z) < len(key_z):
                raw, comp, kind = delta_raw, delta_z, DELTA
        if kind == KEYFRAME:
            self._since_key = 1
            self.stats.keyframes += 1
        else:
            self._since_key += 1
            self.stats.deltas += 1
        ts = timestamp_us(self.stats.frames, self.fps_num, self.fps_den)
        self._fh.write(comp)
        self._index.append(INDEX_ENTRY.pack(self._offset, len(comp), len(raw), ts))
        self._offset += len(comp)
        self.stats.payload_bytes += len(comp)
        self.stats.frames += 1
        self._prev = flat.copy()
        return kind

    def close(self) -> WriteStats:
        if self._fh.closed:
            return self.stats
        if self.stats.frames == 0:
            self._fh.close()
            raise AscfError("cannot write an ASCF file with zero frames")
        index_offset = self._offset
        self._fh.write(b"".join(self._index))
        total = index_offset + INDEX_ENTRY_SIZE * self.stats.frames
        header = HEADER.pack(MAGIC, VERSION_MAJOR, VERSION_MINOR, HEADER_SIZE, self.columns,
                             self.rows, self.stats.frames, self.fps_num, self.fps_den,
                             self.keyframe_interval, len(self.glyphs), HEADER_SIZE,
                             index_offset, total)
        self._fh.seek(0)
        self._fh.write(header)
        self._fh.flush()
        os.fsync(self._fh.fileno())
        self._fh.close()
        self.stats.total_bytes = total
        return self.stats

    def abort(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> "AscfWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.close()
        else:
            self.abort()


# --------------------------------------------------------------------------- reader


@dataclass(frozen=True)
class Header:
    version: tuple[int, int]
    columns: int
    rows: int
    frame_count: int
    fps_num: int
    fps_den: int
    keyframe_interval: int
    glyph_count: int
    glyph_table_offset: int
    index_offset: int
    total_bytes: int

    @property
    def fps(self) -> Fraction:
        return Fraction(self.fps_num, self.fps_den)

    @property
    def duration_us(self) -> int:
        return timestamp_us(self.frame_count, self.fps_num, self.fps_den)


class AscfFile:
    """Validated, seekable view of an ASCF v1 file held in memory."""

    def __init__(self, data: bytes, limits: Limits = DEFAULT_LIMITS):
        self.data = memoryview(data)
        self.limits = limits
        self.header = self._parse_header()
        self.glyphs = self._parse_glyphs()
        self.index = self._parse_index()
        self.cells = self.header.columns * self.header.rows
        self._last: tuple[int, np.ndarray] | None = None
        self._types: dict[int, int] = {}

    @classmethod
    def open(cls, path: str | Path, limits: Limits = DEFAULT_LIMITS) -> "AscfFile":
        p = Path(path)
        size = p.stat().st_size
        if size > limits.max_file_bytes:
            raise AscfError(f"{p} is {size} bytes (limit {limits.max_file_bytes})")
        return cls(p.read_bytes(), limits)

    # -- structure

    def _parse_header(self) -> Header:
        n = len(self.data)
        if n < HEADER_SIZE:
            raise AscfError(f"file too small for an ASCF header ({n} bytes)")
        if n > self.limits.max_file_bytes:
            raise AscfError(f"file is {n} bytes (limit {self.limits.max_file_bytes})")
        (magic, major, minor, hbytes, cols, rows, frames, num, den, kint, gcount, goff, ioff,
         total) = HEADER.unpack_from(self.data, 0)
        L = self.limits
        if magic != MAGIC:
            raise AscfError("not an ASCF file (bad magic)")
        if major != VERSION_MAJOR:
            raise AscfError(f"unsupported ASCF major version {major} (this reader supports 1)")
        if hbytes != HEADER_SIZE:
            raise AscfError(f"unexpected header size {hbytes}")
        if not (1 <= cols <= L.max_columns and 1 <= rows <= L.max_rows):
            raise AscfError(f"grid {cols}x{rows} outside limits")
        if cols * rows > L.max_cells:
            raise AscfError(f"grid has {cols * rows} cells (limit {L.max_cells})")
        if not (1 <= frames <= L.max_frames):
            raise AscfError(f"frame count {frames} outside limits")
        if num == 0 or den == 0:
            raise AscfError("fps numerator/denominator must be non-zero")
        if not (1 <= kint <= L.max_keyframe_interval):
            raise AscfError(f"keyframe interval {kint} outside limits")
        if not (1 <= gcount <= L.max_glyphs):
            raise AscfError(f"glyph count {gcount} outside limits")
        if goff != HEADER_SIZE:
            raise AscfError(f"glyph table offset {goff} must be {HEADER_SIZE}")
        if total != n:
            raise AscfError(f"header says {total} bytes but file has {n} (truncated?)")
        if ioff + frames * INDEX_ENTRY_SIZE != total or ioff < goff + 4:
            raise AscfError("frame index offset/size inconsistent with file size")
        return Header((major, minor), cols, rows, frames, num, den, kint, gcount, goff, ioff, total)

    def _parse_glyphs(self) -> list[str]:
        h = self.header
        (length,) = struct.unpack_from("<I", self.data, h.glyph_table_offset)
        start = h.glyph_table_offset + 4
        if length > self.limits.max_glyph_table_bytes or start + length > h.index_offset:
            raise AscfError("glyph table length out of bounds")
        try:
            glyphs = json.loads(bytes(self.data[start:start + length]).decode("utf-8"))
        except UnicodeDecodeError:
            raise AscfError("glyph table is not valid UTF-8") from None
        except json.JSONDecodeError:
            raise AscfError("glyph table is not valid JSON") from None
        validate_glyph_list(glyphs, self.limits.max_glyphs)
        if len(glyphs) != h.glyph_count:
            raise AscfError(f"glyph table has {len(glyphs)} glyphs, header says {h.glyph_count}")
        self.payload_start = start + length
        return glyphs

    def _parse_index(self) -> np.ndarray:
        h = self.header
        dt = np.dtype([("offset", "<u8"), ("clen", "<u4"), ("ulen", "<u4"), ("ts", "<u8")])
        index = np.frombuffer(self.data, dtype=dt, count=h.frame_count, offset=h.index_offset)
        cells = h.columns * h.rows
        max_ulen = max(1 + cells, 5 + 5 * cells)
        prev_end = self.payload_start
        prev_ts = -1
        for i, (off, clen, ulen, ts) in enumerate(index.tolist()):
            if off < prev_end or off + clen > h.index_offset or clen == 0:
                raise AscfError(f"frame {i}: payload offset/length out of bounds")
            if not (5 <= ulen <= max_ulen) and ulen != 1 + cells:
                raise AscfError(f"frame {i}: implausible uncompressed length {ulen}")
            if ts <= prev_ts:
                raise AscfError(f"frame {i}: timestamps are not strictly increasing")
            prev_end, prev_ts = off + clen, ts
        return index

    # -- payloads

    def payload(self, i: int) -> bytes:
        if not (0 <= i < self.header.frame_count):
            raise AscfError(f"frame {i} out of range")
        off, clen, ulen = (int(self.index[i][k]) for k in ("offset", "clen", "ulen"))
        d = zlib.decompressobj()
        try:
            raw = d.decompress(bytes(self.data[off:off + clen]), ulen + 1)
        except zlib.error as exc:
            raise AscfError(f"frame {i}: corrupt zlib data ({exc})") from None
        if len(raw) != ulen or not d.eof or d.unconsumed_tail or d.unused_data:
            raise AscfError(f"frame {i}: decompressed size mismatch or truncated stream")
        return raw

    def frame_type(self, i: int) -> int:
        if i not in self._types:
            self._types[i] = self.payload(i)[0]
        return self._types[i]

    def _apply(self, i: int, raw: bytes, base: np.ndarray | None) -> np.ndarray:
        kind = raw[0]
        gcount = len(self.glyphs)
        if kind == KEYFRAME:
            if len(raw) != 1 + self.cells:
                raise AscfError(f"frame {i}: keyframe has wrong length")
            grid = np.frombuffer(raw, dtype=np.uint8, offset=1).copy()
        elif kind == DELTA:
            if base is None:
                raise AscfError(f"frame {i}: delta frame without a preceding keyframe")
            (count,) = struct.unpack_from("<I", raw, 1)
            if len(raw) != 5 + 5 * count or count > self.cells:
                raise AscfError(f"frame {i}: delta record count inconsistent with length")
            rec = np.frombuffer(raw, dtype=DELTA_RECORD, count=count, offset=5)
            cells = rec["cell"]
            if count and (cells[-1] >= self.cells or np.any(np.diff(cells.astype(np.int64)) <= 0)):
                raise AscfError(f"frame {i}: delta cells out of range, unsorted or duplicated")
            grid = base.copy()
            grid[cells] = rec["glyph"]
        else:
            raise AscfError(f"frame {i}: unknown frame type 0x{kind:02x}")
        if grid.size and int(grid.max()) >= gcount:
            raise AscfError(f"frame {i}: glyph index out of range")
        self._types[i] = kind
        return grid

    def frame(self, i: int) -> np.ndarray:
        """Decoded (rows, columns) grid for frame ``i`` (seeks via the nearest keyframe)."""
        h = self.header
        if not (0 <= i < h.frame_count):
            raise AscfError(f"frame {i} out of range")
        key = self._find_keyframe(i)
        if self._last is not None and key <= self._last[0] <= i:
            start, grid = self._last[0] + 1, self._last[1]  # continue from the cached frame
        else:
            start, grid = key, None
        for j in range(start, i + 1):
            grid = self._apply(j, self.payload(j), grid)
        self._last = (i, grid)
        return grid.reshape(h.rows, h.columns)

    def _find_keyframe(self, i: int) -> int:
        key_len = 1 + self.cells
        for j in range(i, -1, -1):
            # Keyframes have a fixed uncompressed length; confirm by type byte.
            if int(self.index[j]["ulen"]) == key_len and self.frame_type(j) == KEYFRAME:
                return j
        raise AscfError("no keyframe precedes the requested frame")

    def timestamps_exact(self) -> bool:
        h = self.header
        expected = np.array([timestamp_us(i, h.fps_num, h.fps_den) for i in range(h.frame_count)],
                            dtype=np.uint64)
        return bool(np.array_equal(self.index["ts"], expected))

    def validate_all(self) -> dict:
        """Decode every frame in order; return a summary or raise AscfError."""
        self._last = None
        keys = deltas = 0
        since_key = 0
        h = self.header
        for i in range(h.frame_count):
            grid = self.frame(i)
            if self._types[i] == KEYFRAME:
                keys += 1
                since_key = 1
            else:
                deltas += 1
                since_key += 1
                if since_key > h.keyframe_interval:
                    raise AscfError(f"frame {i}: more than {h.keyframe_interval} frames "
                                    "since the last keyframe")
            del grid
        if self.frame_type(0) != KEYFRAME:
            raise AscfError("frame 0 must be a keyframe")
        return {"keyframes": keys, "deltas": deltas}
