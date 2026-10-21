# ASCII Film — Zero-to-One Build Specification

**Status:** Implementation-ready foundation plan  
**Version:** 1.0  
**Target:** A local, deterministic video-to-typographic-animation encoder plus a static, browser-based player.  
**Primary constraint:** All video analysis and transcoding happen locally, before deployment. The public website only downloads and plays precomputed character data and audio.

---

## 1. Mission and definition of done

Build a production-quality system that turns a conventional video into a moving image made of **actual typographic characters**. Its aesthetic reference is dense, photographic text art: tonal structure emerges from varied glyph shapes and weights, not merely from giant block characters. The website must render the precomputed animation in HTML Canvas, without analyzing or transcoding the original video.

**Version 1 is complete when:**

1. A developer can install the encoder on macOS and run one documented command against a local MP4/MOV.
2. The encoder produces a self-contained, static publish directory containing an animation file, metadata, optional audio, and a web player.
3. Opening that directory through a static HTTP server plays the artwork with accurate timing, pause/play, seek, loop, fullscreen, and responsive resizing.
4. The displayed image is composed of individually drawn glyphs, not a rasterized video masquerading as ASCII.
5. A dense monochrome mode resembles the supplied text-art reference, with adjustable offline rendering controls and repeatable results.
6. A video with no audio works; a video with audio plays in sync; unsupported files fail clearly.
7. The project has automated unit/integration tests, sample fixtures, documentation, and a reproducible deployment procedure.

### Non-goals for v1

No video uploads to the website; no in-browser transcoding; no cloud backend; no user accounts; no database; no AI inference; no livestream or webcam; no mobile app; no browser-side MP4 export; no editing original footage on the website. A local preview may exist but is not a separate editing application.

## 2. Product architecture

```text
LOCAL AUTHORING MACHINE                         STATIC HOST / VISITOR
source.mov
    |
    v
FFmpeg/ffprobe -> frame sampling -> tonal analysis
    -> glyph selection -> temporal stabilization
    -> keyframes/delta frames -> compressed .ascf
    -> manifest.json + optional audio.m4a
    -> dist/<film-id>/
                                      deploy ---> index.html
                                                 player.js / player.css
                                                 film.ascf
                                                 manifest.json
                                                 audio.m4a (optional)
                                                       |
                                                       v
                                                 HTML Canvas glyph rendering
```

**Separation of concerns:** The encoder never requires a browser. The player never requires FFmpeg. The publishing directory can be served by any static host with HTTP range support preferred but not required.

## 3. Chosen technology and repository layout

Use **Python 3.12+** for the offline encoder, **FFmpeg/ffprobe** installed locally for media handling, **NumPy** and **Pillow** for pixel analysis and font rasterization, and **vanilla JavaScript (ES modules), HTML, CSS, and Canvas 2D** for playback. Use Python standard-library `struct` and `zlib` for the binary container. Keep dependency count small. This deliberately favors a reliable, understandable v1 over a premature Rust/Metal optimization. If profiling identifies a real bottleneck, replace only the slow module later.

```text
ascii-film/
  README.md
  build.md
  pyproject.toml
  .gitignore
  encoder/
    __init__.py
    cli.py
    probe.py
    frames.py
    glyphs.py
    mapping.py
    temporal.py
    container.py
    package.py
  web/
    index.html
    player.js
    decoder.js
    renderer.js
    player.css
  assets/
    fonts/README.md
  examples/
    demo-config.json
  tests/
    test_mapping.py
    test_container.py
    test_temporal.py
    test_cli.py
    test_web.mjs
    fixtures/
  scripts/
    make-fixture.sh
    serve.sh
  dist/                 # generated; gitignored
```

Pin Python dependencies in a lockfile or fully pinned requirements. Use Node's built-in test runner for pure JavaScript tests; do not require a JS framework or bundler. Browser end-to-end tests may use Playwright as a **dev-only** dependency.

## 4. User-facing workflow

1. Install prerequisites: Python 3.12+, FFmpeg with ffprobe, and project dependencies.
2. Run `ascii-film encode input.mp4 --output dist/my-film --config examples/demo-config.json`.
3. The CLI probes duration, frame rate, resolution, rotation, and audio streams; validates the requested output; and prints an estimated frame count and grid size.
4. The encoder processes frames offline, reports progress, packages audio if present, writes the animation and manifest atomically, and copies the web player.
5. Preview with `python3 -m http.server 8000 --directory dist/my-film`, then open `http://localhost:8000`.
6. Upload the **contents** of `dist/my-film/` to a static hosting directory. No backend services are necessary.

The CLI must also expose `ascii-film inspect <film.ascf>` to validate header, index, dimensions, frame count, timestamps, and checksums; and `ascii-film --help` with usable examples.

## 5. Encoder pipeline

### 5.1 Media input and timestamps

Use ffprobe JSON to inspect the source. Reject invalid or zero-duration video and sources with no decodable video stream. Respect display rotation and sample aspect ratio so output is not distorted. Decode frames through an FFmpeg subprocess, with **bounded memory** and explicit subprocess-error handling. For v1, normalize variable-frame-rate input to a user-selected constant output FPS using FFmpeg's `fps` filter; the resulting frame timestamps are `frame_index / fps`. Default `fps=24`; permit 1–60. Document that this is a resampling operation and may duplicate/drop source frames.

Use `scale`/`setsar=1` where appropriate, but keep image sampling independent of the character grid. Avoid decoding the entire movie into RAM or storing raw PNG frames by default.

### 5.2 Character geometry

Expose `columns` (default 160; range 40–320) and derive rows from the video's display aspect ratio and **measured glyph cell aspect ratio**:

`rows = round(columns * source_height / source_width * cell_width / cell_height)`.

Measure the selected monospaced font at the configured size with Pillow. Record `cell_width`, `cell_height`, font identity, and effective grid dimensions in the manifest. If the supplied font is not genuinely fixed-pitch, fail validation or require explicit override. Character grid cells are rectangular; do not assume square pixels. Clamp rows to a reasonable bound (e.g., 20–240) and warn when clamped.

### 5.3 Image-to-glyph mapping

Start with a deterministic monochrome photographic mode:

- Convert each frame to linear-light luminance or a documented perceptual approximation.
- Resample to a cell grid using area averaging; expose brightness, contrast, and gamma controls.
- Calibrate each candidate glyph's **actual ink coverage** by rendering it with the selected font to a cell bitmap and measuring average darkness. Sort by calibrated coverage; never assume ASCII character order corresponds to brightness.
- Map each cell's darkness to the nearest calibrated glyph. Use a carefully chosen default set spanning whitespace, punctuation, numerals, and letters (e.g., ` .,:;irsXA253hMHGS#9B&@`), but sort by measured coverage rather than literal order.
- Preserve the source's light/dark polarity. Provide `--invert` for reversed polarity.
- Add optional local edge weighting to preserve facial features and silhouettes. Keep this off by default until tested against reference imagery.
- Optional ordered dithering may improve gradation; make it deterministic and configurable.

**Critical:** Character mapping should preserve local form and tonal continuity. Do not replace every dark region with a single repeated `@` glyph. Provide a density-preserving mode with calibrated coverage and mild spatial variation, seeded for reproducibility.

### 5.4 Temporal stability

Independent per-frame mapping can cause distracting glyph flicker. Implement per-cell hysteresis: retain the previous glyph unless the new target darkness crosses a configurable threshold beyond the old glyph's coverage. Add an optional lightweight temporal low-pass on cell luminance. Defaults must balance stable texture with responsiveness to cuts and movement. Reset temporal state on a detected hard cut or explicit scene boundary. **Do not** stabilize across a cut. Provide `--stability` from 0 to 1, default approximately 0.25, and a `--no-stabilization` switch.

### 5.5 Color mode

V1 must deliver monochrome. Optional color ASCII is a **stretch feature**, not a blocker. If implemented, quantize RGB per cell and store colors as a separate indexed palette stream; do not quietly change the binary spec without a version bump.

## 6. Binary animation format: ASCF v1

Use a **documented, versioned binary format** rather than thousands of individual files. For simplicity and robust seeking, v1 stores independently compressed chunks for every frame, with periodic keyframes and delta frames. All integers are little-endian. Define exact limits and reject corrupt inputs.

### 6.1 Header (fixed 64 bytes)

| Offset | Type | Field |
|---:|---|---|
| 0 | 4 bytes | ASCII magic `ASCF` |
| 4 | uint16 | major version = 1 |
| 6 | uint16 | minor version = 0 |
| 8 | uint32 | header bytes = 64 |
| 12 | uint32 | columns |
| 16 | uint32 | rows |
| 20 | uint32 | frame count |
| 24 | uint32 | fps numerator |
| 28 | uint32 | fps denominator |
| 32 | uint32 | keyframe interval (default 48) |
| 36 | uint32 | glyph count |
| 40 | uint64 | glyph table offset |
| 48 | uint64 | frame index offset |
| 56 | uint64 | total file bytes |

Validate `fps_denominator != 0`, grid/frame limits, and offsets before allocating memory. File layout: header, UTF-8 glyph table, frame payloads, frame index. Glyph table is a uint32 byte length followed by UTF-8 encoded JSON array of Unicode **single-codepoint, non-combining** glyph strings; header `glyph_count` must match array length. Restrict v1 to at most 256 glyphs; each grid cell stores a uint8 glyph index. Reserve index 0 for the space glyph. Reject unsupported Unicode glyphs rather than misrendering them.

### 6.2 Frame payloads

Each frame is an independent zlib-compressed payload with a frame type byte in the uncompressed payload:

- **Keyframe (`0x00`)**: byte `0x00`, then exactly `columns * rows` uint8 glyph indices in row-major order.
- **Delta (`0x01`)**: byte `0x01`, uint32 changed-cell count, then that many `(uint32 cell_index, uint8 glyph_index)` records sorted by cell index, with no duplicates.

Choose delta only when smaller than a keyframe **after compression**. Always insert a keyframe at frame 0 and at least every `keyframe_interval` frames. Keep delta dependencies bounded by the last keyframe. Each index entry is **24 bytes**: `uint64 payload_offset`, `uint32 compressed_length`, `uint32 uncompressed_length`, `uint64 timestamp_us`. The frame type is recovered from the decompressed payload. The index contains exactly `frame_count` entries. All timestamps must be monotonic; for CFR output calculate them using integer arithmetic from FPS rational, not cumulative floating-point addition. No checksums in v1: rely on zlib integrity plus structural validation, and document this explicitly. A future revision may add per-chunk checksums.

### 6.3 Browser decompression

Modern browsers offer `DecompressionStream('deflate')` for zlib-wrapped streams; feature-detect it. For browsers without this API, show an explicit unsupported-browser message in v1 rather than silently failing. Do not accidentally emit raw DEFLATE if the browser expects zlib framing. Test compatibility in current Chrome, Firefox, and Safari.

### 6.4 Seeking and streaming

The player may initially download the complete `.ascf` for v1. Implement the decoder around indexed frames so HTTP range fetching can be added later without redesign. Seeking finds the nearest prior keyframe, then applies deltas through the target frame. Cache the last decoded frame and a small LRU of decoded keyframes. Enforce a configurable memory cap. A full-file fetch is acceptable for short films; warn in the README that long/high-resolution films may produce large files.

## 7. Manifest and publish package

Write `manifest.json` with this stable v1 shape:

```json
{
  "schemaVersion": 1,
  "title": "ASCII Film",
  "animation": "film.ascf",
  "audio": "audio.m4a",
  "durationSeconds": 12.5,
  "fps": {"numerator": 24, "denominator": 1},
  "columns": 160,
  "rows": 68,
  "frameCount": 300,
  "font": {"family": "DejaVu Sans Mono", "file": "font.woff2", "cellWidth": 10, "cellHeight": 18},
  "theme": {"foreground": "#eeeeee", "background": "#101010"},
  "loop": true
}
```

If no audio exists, use `"audio": null`. Ensure `durationSeconds` agrees with the generated animation timeline. Ship a **properly licensed, bundled webfont** in WOFF2 and the matching local TTF/OTF used for glyph calibration; include license text and verify that webfont rendering matches the calibration metrics. Do not assume fonts installed on the viewer's machine. If a font cannot legally be redistributed, require a replacement before publishing. All paths are relative; the player must work under a subdirectory as well as a domain root.

Audio: extract or transcode the original soundtrack to broadly compatible AAC-LC in an `.m4a` container using FFmpeg, align audio start to animation time zero, trim/pad only when necessary, and document any sync offset. Never put source video in the publish directory.

## 8. Browser player behavior

**Layout:** Minimal, artwork-first, black/dark background, no visible controls until hover/tap or keyboard interaction. Canvas scales to fit the viewport while preserving the character grid's measured aspect ratio. Keep glyphs crisp on HiDPI displays; recompute backing resolution on resize and devicePixelRatio changes. Render glyphs at cell positions with `textBaseline` and a loaded, fixed font; avoid subpixel drift and blurred CSS transforms. Offer optional foreground/background color controls that do **not** modify the stored animation.

**Playback controls:** play/pause, progress and scrub, current time/duration, mute/volume when audio exists, loop toggle, fullscreen, keyboard shortcuts (Space, arrows, M, F), accessible labels and focus indicators, reduced-motion handling, and clear loading/error states. Respect browser autoplay restrictions: default to a user-initiated play action when audio exists. For silent films, autoplay muted may be enabled by configuration.

**Timing:** Audio is the master clock when present (`audio.currentTime`), otherwise use a `performance.now()`-based monotonic clock. Render the frame for `floor(time * fps_num / fps_den)` with bounds checks; use `requestAnimationFrame` only to schedule drawing, **not** to count video frames. If late, skip obsolete frames rather than slowing the film. Seeking must update audio and video together. Handle visibility changes, pause/resume, stalled audio, and end-of-media without drifting. Do not assume `requestAnimationFrame` runs in background tabs.

**Canvas performance:** Pre-render each glyph once into a small atlas canvas for the selected font, color, and device pixel ratio; use `drawImage` from the atlas to draw cells. Cache the last displayed glyph grid and redraw only changed cells when appropriate, but force a full redraw on resize, seek, theme changes, or backing-store reset. At typical densities (160 columns, ~60–100 rows), aim for fluid 24–30 FPS on a modern laptop; profile before promising 60 FPS.

**Accessibility:** The artwork is primarily visual; provide descriptive alt text outside the canvas, keyboard-accessible controls, and a pause control. Do not expose thousands of changing glyphs to screen readers as live text.

## 9. CLI and configuration contract

```bash
ascii-film encode source.mp4 \
  --output dist/my-film \
  --fps 24 \
  --columns 160 \
  --font assets/fonts/DejaVuSansMono.ttf \
  --glyphs ' .,:;irsXA253hMHGS#9B&@' \
  --contrast 1.10 \
  --gamma 1.0 \
  --stability 0.25 \
  --keyframe-interval 48 \
  --title 'My ASCII Film'

ascii-film inspect dist/my-film/film.ascf
```

Provide equivalent JSON config options, with CLI flags overriding config values. Use descriptive errors for missing FFmpeg, missing font, unsupported source, invalid characters, bad ranges, insufficient disk space, and failed subprocesses. Print source info, target grid, estimated workload, progress, elapsed time, output size, and generated preview URL instructions. Write into a temporary staging directory, then atomically rename on success; avoid leaving half-published output on failure. Overwrite existing output only with `--force`.

## 10. Security, privacy, and robustness

- Local-only media processing: no telemetry, network calls, or cloud uploads.
- Do not execute shell commands by concatenating user-controlled paths; pass subprocess arguments as arrays.
- Validate every manifest field, glyph table, index offset, decompressed length, and cell index before use.
- Impose configurable caps on file size, grid dimensions, frame count, glyph count, and decompressed data size to prevent excessive allocation.
- Treat title and other metadata as untrusted text; use `textContent`, never unsafe HTML injection.
- Set static-host MIME types correctly for `.js`, `.json`, `.woff2`, `.m4a`; `.ascf` can be `application/octet-stream`.
- Avoid cross-origin dependencies. Host fonts, scripts, data, and audio together by default.
- Preserve the source media's privacy: never copy it into `dist/`.

## 11. Test plan and measurable acceptance criteria

### Python unit tests

- Glyph coverage calibration sorts actual measured darkness correctly; space is lightest.
- Mapping handles pure black, pure white, gradients, contrast/gamma extremes, and invert.
- Grid aspect-ratio formula is correct for representative portrait and landscape inputs.
- Hysteresis reduces flicker on near-threshold sequences and resets at cuts.
- Binary round-trip for all-keyframe, all-delta, mixed, empty-change, and seek-from-keyframe cases.
- Corrupt magic, versions, offsets, lengths, invalid indices, truncated zlib, and invalid UTF-8 fail cleanly.
- Rational timestamp calculation is monotonic and does not accumulate drift.

### Integration tests

- Generate a 5-second synthetic test video with FFmpeg (moving gradient, hard cut, clock marker, optional sine-wave audio).
- Encode with default settings; run `inspect`; assert expected frame count and duration.
- Encode a silent source; verify `audio: null` and functional playback.
- Encode a portrait source; verify correct orientation and aspect ratio.
- Verify output directory contains no original media and is serveable via static HTTP.
- Run identical encoding twice and compare `film.ascf` byte-for-byte; exclude nondeterministic metadata.

### Browser end-to-end tests

- Chrome, Firefox, Safari: load, font readiness, first frame, play, pause, seek backward/forward, loop, resize, fullscreen where supported, audio mute, and keyboard controls.
- Verify playback at 0s, midpoint, and end selects the expected frame index.
- Measure A/V sync against a synthetic clock fixture: target within **100 ms** during normal playback on a modern desktop browser; log failures and environment.
- Test unsupported decompression API and missing/corrupt assets for user-visible errors.
- Verify no browser network requests except static assets under the hosted origin.

### Visual quality gate

Create a short test reel including a face, a landscape, high-contrast text, a dark scene, motion, and a hard cut. Review at 100% and fullscreen. Check that faces remain recognizable, dark regions have tonal variation, glyphs do not shimmer excessively, geometry is not stretched, and no ghosting crosses cuts. Save representative screenshots in test artifacts. Automated pixel tests are supplementary, not a substitute for visual review.

## 12. Implementation order — execute without stopping for approval

**Phase 1 — Foundation:** Initialize repository, pinned environment, CLI entry point, FFmpeg probing, sample-fixture script, configuration validation, and README. Run a real fixture through frame decoding.

**Phase 2 — Image engine:** Implement font calibration, grid sizing, luminance processing, mapping, temporal stabilization, and deterministic frame generation. Produce a human-inspectable ASCII text preview for one frame as a debugging aid.

**Phase 3 — Container:** Implement ASCF writer/reader/validator, keyframes/deltas, timestamps, seek index, compression, and round-trip tests. Add CLI `inspect`.

**Phase 4 — Packaging:** Extract audio, emit manifest, bundle licensed font and static player assets, stage output atomically, and document local preview.

**Phase 5 — Website:** Implement decoder, atlas-based Canvas renderer, audio-master clock, controls, seek, resize, fullscreen, errors, accessibility, and responsive design.

**Phase 6 — Hardening:** Execute integration tests, browser tests, corrupt-file tests, A/V sync checks, performance profiling, and visual quality review. Fix defects, do not merely document them.

**Phase 7 — Delivery:** Include a complete sample film and exact commands for installation, encoding, previewing, and deploying to GitHub Pages or another static host. Provide a short technical report noting actual measured output sizes, FPS, sync behavior, and known limitations.

## 13. Agent execution instructions

You are the implementing software engineer. **Build the working project, not a mockup, proposal, or pseudocode.** Work autonomously through all phases. Choose sensible defaults for unspecified details while preserving the architecture and binary contract above. Commit coherent milestones in Git. Do not introduce a framework, backend, cloud dependency, model inference, or source-video upload flow. Keep modules small and testable. Run the actual encoder and website against generated fixtures before claiming success. If a dependency or environment constraint prevents one test, state precisely what was not verified and supply a reproducible command; do not fabricate passing results. Do not leave TODOs for core v1 behavior. Optimize for correct timing, real glyph fidelity, reliable static deployment, and clean separation between local authoring and web playback.

### Final deliverables

- Complete source repository and dependency/install instructions.
- Working `ascii-film encode` and `ascii-film inspect` commands.
- Documented ASCF v1 encoder and JavaScript decoder.
- Fully static, responsive Canvas website with synchronized optional audio.
- Generated demonstration package in `dist/demo/` (or a clearly documented reproducible generator if binary artifacts are excluded from Git).
- Automated tests and a short report of observed results.
- `README.md` quickstart, hosting instructions, and troubleshooting guide.

## 14. Explicit tradeoffs and future work

This v1 deliberately uses Python and a simple indexed binary format to reduce build risk. Its limitations are acceptable: entire-file download before playback, CFR resampling, monochrome-only output, and browser support tied to `DecompressionStream`. Subsequent versions may add HTTP range streaming, seek-optimized chunk groups, palette color, local GPU encoding, precomputed edge-aware glyph matching, responsive alternate grid resolutions, subtitles, and offline MP4 export. **Do not expand v1 scope until its acceptance criteria pass.**

---

**Product principle:** Encode once, locally. Publish the character data. Play anywhere a modern browser runs. The letters are the picture.
