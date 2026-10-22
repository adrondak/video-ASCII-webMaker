# Technical report — v1.0

Measured on 2026-10-21, MacBook (Apple silicon), macOS 27.0.1, Python 3.13.2,
FFmpeg 9.0.2, Node 22.14, Playwright 1.63.0 (Chromium, WebKit 26.6).

## The demo film (`www/`)

| | |
|---|---|
| Source | `1080ocean.mp4` — H.264 1920×1080, 23.976 fps, 21.35 s, AAC stereo (audio not used) |
| Settings | [`examples/ocean-config.json`](../examples/ocean-config.json): 220 columns, DejaVu Sans Mono Bold, line-height 1.0, 69 glyphs, γ 0.65, detail 0.4, variation 1.0, stability 0.3, 1 s loop crossfade |
| Grid | 220 × 74 cells (16 280 per frame) |
| Frames | 489 at 24 fps = 20.375 s (21.375 s resampled, minus the 1 s crossfade) |
| Keyframes / deltas | 56 / 433 (keyframe interval 48) |
| Payload per frame | 1.1 KB min, 5.8 KB mean, 8.8 KB max (compressed) |
| `film.ascf` | 2.8 MB |
| Whole site | 2.9 MB (font 144 KB, player 38 KB) — zip 2.9 MB |
| Encode time | ~10 s (≈60 fps processing incl. a second decode pass for the crossfade) |
| Loop seam | 17.3 % of cells change from last → first frame; normal frame-to-frame change is 14.0 % median / 20.5 % p95 — the loop point is indistinguishable from an ordinary frame. Without the stabiliser splice it was 70.5 %. |

For comparison, the 240p version of the same clip (`ocean.mp4`) with identical
settings gives 2.6 MB in 9.2 s — usable, but upscaling a 426-px source to the
880-px sampling grid softens the foam. The 1080p source was used for `www/`.
Default settings (160 columns, 23 glyphs) on the 1080p clip give a 0.97 MB
site encoded in 2.5 s.

## Playback performance

`node scripts/profile-player.mjs www 10` — 1920×1080 viewport at
devicePixelRatio 2 (a 3740×2072 canvas, 17×28 device-pixel cells), headless:

| Browser | Frames shown / expected | Skipped | Draw per frame | Decode per frame | Cells redrawn per frame |
|---|---|---|---|---|---|
| Chromium | 240 / 240 | 0 | 1.8 ms | 2.8 ms | ~2 180 of 16 280 |
| WebKit (Safari engine) | 238 / 240 | 0 | 1.0 ms | 1.6 ms | ~2 170 of 16 280 |

Changed-cell redraw means only ~13 % of cells are repainted per frame. The
budget at 24 fps is 41.7 ms, so there is ample headroom for slower laptops and
phones. (WebKit's 2 "missing" frames are the first frame boundary of the
measurement window, not drops: skipped = 0.)

## A/V sync

With `--audio`, the audio element is the master clock and the frame shown is
`floor(audio.currentTime × fps)`. On the synthetic click-track fixture the
worst sampled offset beyond the one-frame quantum was **14.6 ms (Chromium)**
and **12.7 ms (WebKit)** — well inside the 100 ms target. (Audio output
latency of the device is not included; browsers report `currentTime` for what
is being decoded.)

## Test results

| Suite | Result |
|---|---|
| `pytest` (unit + integration: calibration, mapping, aspect, tone extremes, hysteresis, cuts, container round-trips, corrupt-file cases, timestamps, determinism, CLI encode/inspect/preview, portrait + rotated sources, silent source, audio opt-in, `--force`, crossfade) | **84 passed** |
| `npm test` (Node: JS decoder vs Python encoder, seeking, concurrency, corruption) | **8 passed** |
| Playwright Chromium | **13 passed** |
| Playwright WebKit | **13 passed** |
| Playwright Firefox | **not run** — see below |

Determinism: encoding the same source twice produces byte-identical
`film.ascf` (tested). `manifest.json` has no timestamps and is also stable.

## What was not verified

* **Firefox.** Playwright's Firefox (both 1.56 and 1.63 builds) failed to
  start inside the build machine's command sandbox ("Could not find profile
  folder"), and running outside the sandbox was not permitted. The player uses
  only standard APIs Firefox supports (`DecompressionStream` since 113,
  `OffscreenCanvas`, `FontFace`). Reproduce with:
  `npm run e2e -- --project=firefox`.
* **Real Safari / iOS devices** — WebKit was tested headless only. iPhone
  Safari has no element fullscreen API; the player hides that button there.
* **A live SiteGround account** — the site was verified on a local
  Range-capable static server; the `.htaccess` uses only directives guarded by
  `<IfModule>`. Deployment steps are in [SITEGROUND.md](SITEGROUND.md).
* **Visual quality gate** — the spec's test reel (faces, text, dark scenes)
  was not available; only the ocean clip and synthetic fixtures were reviewed.
  Faces in particular would benefit from a review with `--detail` 0.3–0.8.

## Known limitations

* The whole film downloads before playback (2.8 MB here). The decoder is
  index-based, so HTTP range streaming can be added without format changes.
* Constant frame rate only (variable-rate input is resampled).
* Monochrome; no colour stream in ASCF v1.
* `loop_crossfade` and `--audio` cannot be combined (the soundtrack is not
  dissolved).
* Hysteresis is tuned per film by `--stability`; very fast motion at high
  stability can lag a few frames behind.
