// ASCF v1 decoder. Pure ES module: runs in browsers and in Node 18+ (tests).
//
// Layout: 64-byte header | u32 length + UTF-8 JSON glyph table | zlib frame
// payloads | frame index (24 bytes per frame). See encoder/container.py.
// Payloads use zlib framing (RFC 1950), which DecompressionStream calls
// "deflate" (raw DEFLATE would be "deflate-raw").

export const HEADER_SIZE = 64;
export const INDEX_ENTRY_SIZE = 24;
export const KEYFRAME = 0x00;
export const DELTA = 0x01;

export const DEFAULT_LIMITS = Object.freeze({
  maxColumns: 4096,
  maxRows: 4096,
  maxCells: 1 << 22,
  maxFrames: 1_000_000,
  maxGlyphs: 256,
  maxGlyphTableBytes: 64 * 1024,
  maxFileBytes: 512 * 1024 * 1024,
  maxKeyframeInterval: 100_000,
  keyframeCacheEntries: 8,
  cacheBytes: 32 * 1024 * 1024,
});

export class AscfError extends Error {
  constructor(message) {
    super(message);
    this.name = "AscfError";
  }
}

export function supportsDecompression() {
  return typeof DecompressionStream === "function";
}

function u64(view, offset) {
  const value = view.getBigUint64(offset, true);
  if (value > BigInt(Number.MAX_SAFE_INTEGER)) throw new AscfError("64-bit field out of range");
  return Number(value);
}

/** Inflate a zlib stream, refusing to produce more than `expected` bytes. */
export async function inflate(bytes, expected) {
  if (!supportsDecompression()) throw new AscfError("DecompressionStream is not supported");
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate"));
  const reader = stream.getReader();
  const out = new Uint8Array(expected);
  let got = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (got + value.length > expected) {
        await reader.cancel().catch(() => {});
        throw new AscfError("payload decompresses to more bytes than its index entry says");
      }
      out.set(value, got);
      got += value.length;
    }
  } catch (err) {
    if (err instanceof AscfError) throw err;
    throw new AscfError(`corrupt zlib payload (${err && err.message ? err.message : err})`);
  }
  if (got !== expected) throw new AscfError(`payload is ${got} bytes, index says ${expected}`);
  return out;
}

function validateGlyphs(glyphs, maxGlyphs) {
  if (!Array.isArray(glyphs) || glyphs.length === 0) throw new AscfError("glyph table must be a non-empty array");
  if (glyphs.length > maxGlyphs) throw new AscfError("too many glyphs");
  const seen = new Set();
  for (const g of glyphs) {
    if (typeof g !== "string" || [...g].length !== 1) throw new AscfError(`glyph ${JSON.stringify(g)} is not one code point`);
    if (/\p{M}|\p{Cc}|\p{Cs}/u.test(g)) throw new AscfError("glyph table contains a combining or control character");
    if (seen.has(g)) throw new AscfError("glyph table contains duplicates");
    seen.add(g);
  }
  if (glyphs[0] !== " ") throw new AscfError("glyph index 0 must be the space glyph");
  return glyphs;
}

export class AscfDecoder {
  /** @param {ArrayBuffer} buffer complete .ascf file */
  constructor(buffer, limits = {}) {
    this.limits = { ...DEFAULT_LIMITS, ...limits };
    if (!(buffer instanceof ArrayBuffer)) throw new AscfError("expected an ArrayBuffer");
    this.buffer = buffer;
    this.view = new DataView(buffer);
    this._parseHeader();
    this._parseGlyphs();
    this._parseIndex();
    this.types = new Int8Array(this.frameCount).fill(-1);
    this.last = null; // { i, grid }
    this.keyCache = new Map(); // keyframe index -> grid, least recently used first
    this.queue = Promise.resolve();
  }

  _parseHeader() {
    const L = this.limits;
    const n = this.buffer.byteLength;
    if (n < HEADER_SIZE) throw new AscfError(`file too small for an ASCF header (${n} bytes)`);
    if (n > L.maxFileBytes) throw new AscfError(`file is ${n} bytes (limit ${L.maxFileBytes})`);
    const v = this.view;
    const magic = String.fromCharCode(v.getUint8(0), v.getUint8(1), v.getUint8(2), v.getUint8(3));
    if (magic !== "ASCF") throw new AscfError("not an ASCF file (bad magic)");
    this.versionMajor = v.getUint16(4, true);
    this.versionMinor = v.getUint16(6, true);
    if (this.versionMajor !== 1) throw new AscfError(`unsupported ASCF major version ${this.versionMajor}`);
    if (v.getUint32(8, true) !== HEADER_SIZE) throw new AscfError("unexpected header size");
    this.columns = v.getUint32(12, true);
    this.rows = v.getUint32(16, true);
    this.frameCount = v.getUint32(20, true);
    this.fpsNum = v.getUint32(24, true);
    this.fpsDen = v.getUint32(28, true);
    this.keyframeInterval = v.getUint32(32, true);
    this.glyphCount = v.getUint32(36, true);
    this.glyphTableOffset = u64(v, 40);
    this.indexOffset = u64(v, 48);
    this.totalBytes = u64(v, 56);
    this.cells = this.columns * this.rows;
    if (!(this.columns >= 1 && this.columns <= L.maxColumns && this.rows >= 1 && this.rows <= L.maxRows)) throw new AscfError("grid size outside limits");
    if (this.cells > L.maxCells) throw new AscfError("too many cells");
    if (!(this.frameCount >= 1 && this.frameCount <= L.maxFrames)) throw new AscfError("frame count outside limits");
    if (this.fpsNum === 0 || this.fpsDen === 0) throw new AscfError("fps numerator/denominator must be non-zero");
    if (!(this.keyframeInterval >= 1 && this.keyframeInterval <= L.maxKeyframeInterval)) throw new AscfError("keyframe interval outside limits");
    if (!(this.glyphCount >= 1 && this.glyphCount <= L.maxGlyphs)) throw new AscfError("glyph count outside limits");
    if (this.glyphTableOffset !== HEADER_SIZE) throw new AscfError("unexpected glyph table offset");
    if (this.totalBytes !== n) throw new AscfError(`header says ${this.totalBytes} bytes but file has ${n} (truncated?)`);
    if (this.indexOffset + this.frameCount * INDEX_ENTRY_SIZE !== n || this.indexOffset < HEADER_SIZE + 4) throw new AscfError("frame index offset inconsistent with file size");
  }

  _parseGlyphs() {
    const len = this.view.getUint32(this.glyphTableOffset, true);
    const start = this.glyphTableOffset + 4;
    if (len > this.limits.maxGlyphTableBytes || start + len > this.indexOffset) throw new AscfError("glyph table length out of bounds");
    let glyphs;
    try {
      const text = new TextDecoder("utf-8", { fatal: true }).decode(new Uint8Array(this.buffer, start, len));
      glyphs = JSON.parse(text);
    } catch {
      throw new AscfError("glyph table is not valid UTF-8 JSON");
    }
    this.glyphs = validateGlyphs(glyphs, this.limits.maxGlyphs);
    if (this.glyphs.length !== this.glyphCount) throw new AscfError("glyph count does not match header");
    this.payloadStart = start + len;
  }

  _parseIndex() {
    const n = this.frameCount;
    this.offsets = new Float64Array(n);
    this.clens = new Uint32Array(n);
    this.ulens = new Uint32Array(n);
    this.timestamps = new Float64Array(n);
    const maxUlen = Math.max(1 + this.cells, 5 + 5 * this.cells);
    let prevEnd = this.payloadStart;
    let prevTs = -1;
    for (let i = 0; i < n; i++) {
      const base = this.indexOffset + i * INDEX_ENTRY_SIZE;
      const off = u64(this.view, base);
      const clen = this.view.getUint32(base + 8, true);
      const ulen = this.view.getUint32(base + 12, true);
      const ts = u64(this.view, base + 16);
      if (off < prevEnd || off + clen > this.indexOffset || clen === 0) throw new AscfError(`frame ${i}: payload out of bounds`);
      if (ulen > maxUlen || (ulen < 5 && ulen !== 1 + this.cells)) throw new AscfError(`frame ${i}: implausible uncompressed length`);
      if (ts <= prevTs) throw new AscfError(`frame ${i}: timestamps are not strictly increasing`);
      this.offsets[i] = off;
      this.clens[i] = clen;
      this.ulens[i] = ulen;
      this.timestamps[i] = ts;
      prevEnd = off + clen;
      prevTs = ts;
    }
  }

  get fps() {
    return this.fpsNum / this.fpsDen;
  }

  get durationSeconds() {
    return (this.frameCount * this.fpsDen) / this.fpsNum;
  }

  /** Frame shown at `seconds`, clamped to the film: floor(t * num / den). */
  frameAt(seconds) {
    const i = Math.floor((seconds * this.fpsNum) / this.fpsDen + 1e-9);
    return Math.min(Math.max(i, 0), this.frameCount - 1);
  }

  async payload(i) {
    const bytes = new Uint8Array(this.buffer, this.offsets[i], this.clens[i]);
    const raw = await inflate(bytes, this.ulens[i]);
    this.types[i] = raw[0];
    return raw;
  }

  _apply(i, raw, base) {
    const kind = raw[0];
    let grid;
    if (kind === KEYFRAME) {
      if (raw.length !== 1 + this.cells) throw new AscfError(`frame ${i}: keyframe has wrong length`);
      grid = raw.slice(1);
      for (let k = 0; k < grid.length; k++) if (grid[k] >= this.glyphCount) throw new AscfError(`frame ${i}: glyph index out of range`);
    } else if (kind === DELTA) {
      if (!base) throw new AscfError(`frame ${i}: delta frame without a preceding keyframe`);
      const dv = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
      const count = dv.getUint32(1, true);
      if (raw.length !== 5 + 5 * count || count > this.cells) throw new AscfError(`frame ${i}: delta length inconsistent`);
      grid = base.slice();
      let prev = -1;
      for (let r = 0, p = 5; r < count; r++, p += 5) {
        const cell = dv.getUint32(p, true);
        const glyph = raw[p + 4];
        if (cell <= prev || cell >= this.cells) throw new AscfError(`frame ${i}: delta cells unsorted or out of range`);
        if (glyph >= this.glyphCount) throw new AscfError(`frame ${i}: glyph index out of range`);
        grid[cell] = glyph;
        prev = cell;
      }
    } else {
      throw new AscfError(`frame ${i}: unknown frame type ${kind}`);
    }
    return grid;
  }

  async _findKeyframe(i) {
    const keyLen = 1 + this.cells;
    for (let j = i; j >= 0; j--) {
      if (this.ulens[j] !== keyLen) continue;
      if (this.types[j] === -1) await this.payload(j);
      if (this.types[j] === KEYFRAME) return j;
    }
    throw new AscfError("no keyframe precedes the requested frame");
  }

  _remember(key, grid) {
    this.keyCache.delete(key);
    this.keyCache.set(key, grid);
    const maxEntries = Math.max(1, Math.min(this.limits.keyframeCacheEntries,
      Math.floor(this.limits.cacheBytes / Math.max(this.cells, 1))));
    while (this.keyCache.size > maxEntries) this.keyCache.delete(this.keyCache.keys().next().value);
  }

  async _decode(i) {
    if (!(Number.isInteger(i) && i >= 0 && i < this.frameCount)) throw new AscfError(`frame ${i} out of range`);
    if (this.last && this.last.i === i) return this.last.grid;
    const key = await this._findKeyframe(i);
    let start = key;
    let grid = null;
    if (this.last && key <= this.last.i && this.last.i < i) {
      start = this.last.i + 1;
      grid = this.last.grid;
    } else if (this.keyCache.has(key)) {
      grid = this.keyCache.get(key);
      this._remember(key, grid);
      start = key + 1;
    }
    for (let j = start; j <= i; j++) {
      grid = this._apply(j, await this.payload(j), grid);
      if (this.types[j] === KEYFRAME) this._remember(j, grid);
    }
    this.last = { i, grid };
    return grid;
  }

  /**
   * Decoded glyph-index grid (Uint8Array, row-major) for frame i. Requests are
   * serialised; returned arrays are never mutated afterwards.
   */
  frame(i) {
    const result = this.queue.then(() => this._decode(i));
    this.queue = result.catch(() => {});
    return result;
  }
}
