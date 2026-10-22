# ASCF v1 — ASCII Film binary format

A single file holding a fixed grid of glyph indices over time. All integers
are little-endian. Writer: `encoder/container.py`. Readers:
`encoder/container.py` (Python) and `web/decoder.js` (browser/Node).

```text
┌──────────────┬─────────────────┬───────────────────────┬──────────────────┐
│ header (64B) │ glyph table     │ frame payloads …      │ frame index      │
│              │ u32 len + JSON  │ independent zlib each │ 24 B × frames    │
└──────────────┴─────────────────┴───────────────────────┴──────────────────┘
```

## Header (64 bytes)

| Offset | Type | Field |
|---:|---|---|
| 0 | 4 bytes | magic `ASCF` |
| 4 | u16 | major version = 1 (readers reject other majors) |
| 6 | u16 | minor version = 0 (readers accept any minor) |
| 8 | u32 | header bytes = 64 |
| 12 | u32 | columns |
| 16 | u32 | rows |
| 20 | u32 | frame count |
| 24 | u32 | fps numerator |
| 28 | u32 | fps denominator (non-zero) |
| 32 | u32 | keyframe interval (max frames from one keyframe to the next) |
| 36 | u32 | glyph count (1–256) |
| 40 | u64 | glyph table offset (= 64) |
| 48 | u64 | frame index offset |
| 56 | u64 | total file bytes (must equal the file size) |

## Glyph table

`u32` byte length, then a UTF-8 JSON array of strings. Each entry is exactly
one Unicode code point, not a combining mark or control character; entries are
unique; index 0 is always `" "` (space). Glyphs are stored lightest-first, but
readers must not rely on order.

## Frame payloads

Each payload is an independent zlib stream (RFC 1950 framing — what
`DecompressionStream("deflate")` expects; raw DEFLATE is not used).
Decompressed, the first byte is the frame type:

* **Keyframe `0x00`** — then `columns × rows` u8 glyph indices, row-major.
* **Delta `0x01`** — then u32 changed-cell count *n*, then *n* records of
  `(u32 cell_index, u8 glyph_index)`, strictly increasing by cell index,
  applied to the previous frame.

Frame 0 is a keyframe, and no more than *keyframe interval* frames pass
between keyframes. The encoder writes a delta only when it is smaller than the
keyframe *after* compression, so static scenes are tiny and busy scenes fall
back to keyframes automatically.

## Frame index

`frame count` entries of 24 bytes:

| Offset | Type | Field |
|---:|---|---|
| 0 | u64 | payload offset |
| 8 | u32 | compressed length |
| 12 | u32 | uncompressed length |
| 16 | u64 | timestamp in µs = ⌊i × 1 000 000 × den / num⌋ (integer maths, no drift) |

Payloads are non-overlapping and in file order; timestamps strictly increase.

## Seeking

To show frame *i*: walk back to the nearest keyframe (a keyframe's
uncompressed length is always `1 + cells`; confirm with the type byte, since a
delta can coincidentally have the same length), then apply deltas forward.
Both decoders cache the last decoded frame (so sequential playback costs one
small inflate per frame) and an LRU of decoded keyframes.

## Validation rules (both readers)

Reject before allocating: bad magic or major version, header size ≠ 64,
zero fps, grid/frame/glyph counts beyond configurable limits, offsets outside
the file, `total bytes` ≠ file size, index not ending at EOF, glyph table not
valid UTF-8 JSON or count mismatch, payloads out of bounds or overlapping,
non-increasing timestamps. While decoding: zlib errors, decompressed length ≠
index, unknown frame type, keyframe of the wrong size, delta count/length
mismatch, unsorted/duplicate/out-of-range cells, glyph index ≥ glyph count.

There are no checksums in v1 beyond zlib's Adler-32; a later minor version
could add per-chunk checksums without breaking v1 readers.
