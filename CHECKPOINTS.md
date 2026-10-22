# Checkpoints

This repository was built in seven phases plus one extension, and each phase is an annotated git
tag you can clone on its own. Every checkpoint is a working project at that
stage — its README says what it can do and its tests pass.

```bash
# clone one stage (shallow, just that snapshot)
git clone --branch checkpoint-03-container --depth 1 https://github.com/adrondak/video-ASCII-webMaker.git

# or, in a full clone, compare two stages
git diff checkpoint-04-packaging checkpoint-05-player -- web/
```

| Tag | What it adds | Good starting point if you want to… |
|---|---|---|
| `checkpoint-01-foundation` | Project skeleton, pinned env, bundled licensed font, ffprobe inspection (rotation, SAR), JSON+CLI config validation, synthetic fixture generator, bounded-memory constant-fps frame decoding. | …write your own image→glyph engine on a solid FFmpeg base. |
| `checkpoint-02-image-engine` | Font calibration (glyphs sorted by *measured* ink), grid sizing from the measured cell aspect, linear-light cell averaging, auto-levels, polarity from theme, seeded variation, Bayer dither, shape-aware detail, temporal hysteresis + cut reset, `preview` (text/PNG). | …experiment with glyph mapping and see results instantly as text or PNG. |
| `checkpoint-03-container` | ASCF v1 binary format: zlib keyframes + compressed-size-chosen deltas, exact rational timestamps, validating seekable reader, corruption tests, `inspect`. | …reuse the file format with your own player or language. |
| `checkpoint-04-packaging` | `encode` builds a full static site atomically (film, manifest, WOFF2 + licence, `.htaccess`, opt-in AAC audio) with a deliberately **minimal** 60-line player; JS decoder + Node tests; end-to-end CLI tests. | …see the smallest player that works, before optimisation. |
| `checkpoint-05-player` | Production player: glyph-atlas Canvas renderer at integer device pixels with changed-cell redraw, wall/audio master clock with frame skipping, controls, keyboard, themes, fullscreen, reduced motion, errors; Range-capable preview server; Playwright E2E. | …embed or restyle the player. |
| `checkpoint-06-hardening` | Seamless loops (`loop_crossfade` dissolve + stabiliser splice), playback profiler, server/test fixes. | …make looping installations. |
| `checkpoint-07-delivery` | The finished `www/` ocean site, full README, SiteGround guide, ASCF spec, technical report, zip packaging. | …just use the tool. |
| `checkpoint-08-interaction` | Glyph physics: a cursor lens that parts and magnifies the glyphs, ripples from movement and clicks, underdamped springs that wag glyphs home; block-based repaint with pixel-exact restore; `--lens-*`/`--ripple-*` options. | …make the text-art interactive. |

`main` always points at the latest checkpoint.

## Using a checkpoint

Each one needs the same setup:

```bash
brew install ffmpeg python@3.13 node
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock && pip install -e . --no-deps
scripts/make-fixture.sh && pytest -q
```

then follow that checkpoint's README "Try it" section. Source videos are not
in the repository; use the synthetic fixtures or your own clips.
