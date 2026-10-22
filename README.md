# ASCII Film

[![tests](https://github.com/adrondak/video-ASCII-webMaker/actions/workflows/ci.yml/badge.svg)](https://github.com/adrondak/video-ASCII-webMaker/actions/workflows/ci.yml)
[![live demo](https://img.shields.io/badge/live%20demo-open-2ea44f)](https://adrondak.github.io/video-ASCII-webMaker/)
[![release](https://img.shields.io/github/v/release/adrondak/video-ASCII-webMaker?label=site%20zip)](https://github.com/adrondak/video-ASCII-webMaker/releases/latest)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

**Turn any video clip into a website where the picture is made of real text characters** —
and the letters physically react when you move your mouse over them.

### ▶ [Open the live demo](https://adrondak.github.io/video-ASCII-webMaker/)

<p align="center"><img src="docs/demo.gif" alt="Waves drawn in text characters; a lens of magnified letters follows the cursor and the glyphs ripple and wag back into place" width="560"></p>

Move your mouse over the waves: the letters part and magnify around the cursor,
ripple as it moves, and wobble back into place when it leaves. Click for a
shockwave. Press **T** to change colour (green phosphor, amber, ice), **I** to
turn the physics off, **F** for fullscreen, **Space** to pause.

---

## Pick your path

| You want to… | Do this |
|---|---|
| **Just look at it** | [Open the live demo](https://adrondak.github.io/video-ASCII-webMaker/). Nothing to install. |
| **Put this exact site on your own website** | Download [`ascii-film-ocean-site.zip`](https://github.com/adrondak/video-ASCII-webMaker/releases/latest), upload it to your host and unzip. [SiteGround / cPanel guide](docs/SITEGROUND.md). |
| **Make one from your own video** | [Quick start](#quick-start-macos): install FFmpeg + Python, run one command, upload the folder it makes. |
| **Understand how it works** | [How it works](#how-it-works) below, the [file format spec](docs/ASCF.md), and the [measured results](docs/REPORT.md). |
| **Learn by rebuilding it step by step** | The repo is tagged at every stage, from empty skeleton to finished site: [CHECKPOINTS.md](CHECKPOINTS.md). |
| **Hack on it** | [Contributing](CONTRIBUTING.md) — tests run in CI on every push. |

### What it is (and isn't)

* **Real letters, not a video filter.** Every mark is a glyph from a monospace
  font, drawn one by one on a canvas. No video file is shipped to visitors.
* **Encode once, offline.** A Python tool reads your clip with FFmpeg and
  writes a tiny animation file (2.8 MB for this 20-second, 220×74-glyph film).
* **Plain static website.** HTML + JavaScript + one data file. Works on
  SiteGround, GitHub Pages, Netlify, any web host — no server code, no build step,
  no external requests, no tracking.
* **Loops seamlessly** and starts silently on page load.

![The ocean film rendered in glyphs](docs/ocean-wave.png)

<sub>Close-up at 100% — every mark is a character:</sub>

![Detail of the glyph rendering at 100%](docs/ocean-detail.png)

---

## Live webcam mode — ASCII Mirror (`webcam` branch)

> You are on the `webcam` branch. It adds a second, **separate** site that
> draws your camera live in glyphs, with the same lens and ripples. The film
> site in `www/` is unchanged.

```bash
git switch webcam
ascii-film live --config examples/live-config.json --output www-live --force
scripts/serve.sh www-live        # open http://localhost:8000/ and click "Start camera"
```

* **Everything stays in the browser.** Frames go from the camera to a hidden
  canvas to glyphs and are never stored or sent anywhere. The page does
  nothing until the visitor clicks **Start camera**.
* **Same mapping as the films.** Font calibration happens in Python, exactly
  as for encoded films, and the browser runs a JavaScript port of the tone
  curve, glyph choice, variation and anti-flicker stabiliser
  ([`web/camera.js`](web/camera.js)), with auto-levels smoothed over about
  half a second so exposure changes glide.
* **Controls:** **Space** freeze · **M** mirror · **[ / ]** bigger or smaller
  letters (80–220 columns) · **T** colour theme · **I** lens on/off ·
  **F** fullscreen. Move the cursor to push your own face around.
* **Hosting:** upload `www-live/` like any static site. Browsers only allow
  cameras on `https://` pages (or `localhost`); SiteGround's free Let's Encrypt
  certificate and GitHub Pages both qualify.
* **Speed:** mapping a 140×47 frame takes about 5 ms in Chromium. The
  page runs at the camera's own frame rate.

---

## How it works

```text
YOUR MACHINE (encode once)                                 ANY STATIC HOST (play)
clip.mp4 ─ ffprobe ─ ffmpeg fps+scale ─ linear-light cells ─ tone curve
      ─ glyph match (measured ink + shape) ─ temporal stabiliser
      ─ keyframes/deltas ─ zlib ─ film.ascf + manifest.json ──────▶ index.html
                                                                    player.js  ─ Canvas
                                                                    font.woff2   glyph atlas
```

1. **Calibrate the font.** Every candidate glyph is rendered with the real font
   into one character cell and its ink coverage is measured. Glyphs are sorted
   by *measured* darkness, never by ASCII order.
2. **Sample the video.** FFmpeg resamples to a constant frame rate and scales
   each frame to the character grid × an oversampling factor. Luminance is
   averaged per cell in *linear light* and re-encoded perceptually.
3. **Choose glyphs.** Each cell gets the glyph whose calibrated coverage best
   matches its tone, plus a static seeded variation so flat areas use a mix of
   similar glyphs, and optional shape matching so strokes follow edges.
4. **Stabilise in time.** A light low-pass and per-cell hysteresis stop glyphs
   flickering between neighbours; hard cuts reset the state.
5. **Pack.** Frames are stored in the documented [ASCF v1](docs/ASCF.md)
   binary: zlib keyframes plus delta frames, with an exact timestamp index.
6. **Play.** The browser decompresses frames with `DecompressionStream`, draws
   glyphs from a pre-rendered atlas at integer device pixels, and times frames
   from a wall clock (or the audio element when there is sound).
7. **Touch.** Each glyph is also a damped spring. A Gaussian bulge around the
   pointer pushes glyphs outward and scales them up (a lens made of the
   letters themselves); pointer movement launches ripple rings; underdamped
   springs make every glyph overshoot and wag home. Only 8×8-cell blocks that
   contain visibly moving glyphs are repainted, and resting glyphs are drawn
   from the same tiles as normal frames, so the picture returns pixel-exact.

## Quick start (macOS)

You need [FFmpeg](https://ffmpeg.org), Python 3.12+ and (only for running the
tests) Node 18+. On a Mac with [Homebrew](https://brew.sh):

```bash
brew install ffmpeg python@3.13 node
git clone https://github.com/adrondak/video-ASCII-webMaker.git
cd video-ASCII-webMaker
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock && pip install -e . --no-deps
```

Encode your own clip and preview it:

```bash
ascii-film encode my-clip.mp4 --output dist/my-film --title "My Film"
scripts/serve.sh dist/my-film          # then open http://localhost:8000/
```

Rebuild the demo site exactly as committed (put the source clip in
`assets/video/` first — source media is not part of the repo):

```bash
ascii-film encode assets/video/1080ocean.mp4 --config examples/ocean-config.json --output www --force
```

Linux works the same with your package manager's `ffmpeg`. Windows: use WSL
(Ubuntu) and follow the Linux route.

Want the green look from the demo screenshots by default? Encode with
`--foreground "#5dff8a" --background "#020b05"`.

## Commands

| Command | What it does |
|---|---|
| `ascii-film encode SRC -o DIR` | Build a publish directory (staged, then atomically renamed). |
| `ascii-film inspect FILE.ascf` | Validate header, glyph table, index, timestamps and every frame. |
| `ascii-film preview SRC --time 5 [--png out.png]` | Print (or rasterise) one frame — for tuning settings fast. |
| `ascii-film probe SRC` | Show what ffprobe sees: size, rotation, SAR, fps, audio. |
| `ascii-film live -o DIR` | Build the live webcam page as its own static site (`webcam` branch). |

`ascii-film encode --help` lists every flag. Any option can also live in a JSON
config (`--config file.json`); CLI flags override the file. Paths in a config
file are relative to that file.

### Options that matter most

| Option | Default | Notes |
|---|---|---|
| `--columns` | 160 | 40–320. Rows follow from the video aspect and the font's measured cell. |
| `--fps` | 24 | 1–60. Variable-rate sources are resampled (frames may be duplicated or dropped). |
| `--font` | DejaVu Sans Mono | Must be fixed-pitch and redistributable; a `.woff2` and `LICENSE*` next to it are shipped. |
| `--line-height` | font metrics | In em. `1.0` packs rows tightly for a denser, more photographic look. |
| `--glyphs` | `" .,:;irsXA253hMHGS#9B&@"` | Up to 256 single-codepoint glyphs; order does not matter. |
| `--contrast / --gamma / --brightness` | 1 / 1 / 0 | Applied after automatic levels (`--no-auto-levels` to skip). |
| `--detail` | 0 | Shape matching strength. 0.3–0.6 sharpens edges; higher favours thin strokes. |
| `--variation` | 0.35 | Seeded per-cell texture among similar-coverage glyphs (`--seed`). |
| `--dither` | 0 | Ordered 4×4 dither between neighbouring glyphs. |
| `--stability` | 0.25 | 0–1; `--no-stabilization` to turn off. Hard cuts always reset. |
| `--loop-crossfade` | 0 | Seconds of the ending dissolved into the opening for a seamless loop. |
| `--foreground / --background` | `#eeeeee` / `#101010` | Light-on-dark keeps the source polarity; dark-on-light inverts mapping automatically. `--invert` flips it. |
| `--autoplay` | `muted` | `muted` starts on load and loops; `off` waits for a click. |
| `--audio` | off | Opt-in: package the soundtrack as AAC `audio.m4a`; it then becomes the master clock. |
| `--no-lens` / `--no-ripples` | on / on | Turn off the cursor lens or the ripples. |
| `--lens-radius` | 7 | Lens radius in cell widths. |
| `--lens-strength` | 1.4 | Push and magnification: the centre is magnified 1 + this (0–2.2). |
| `--ripple-strength` | 1 | Multiplier on how hard ripples push and swell glyphs (0–4). |

The demo's settings are in [`examples/ocean-config.json`](examples/ocean-config.json).

## The publish directory

```text
www/
  index.html  player.css  player.js  decoder.js  renderer.js  field.js  ← the player (no dependencies)
  film.ascf                                                    ← the animation
  manifest.json                                                ← grid, timing, font metrics, theme
  font.woff2  FONT-LICENSE.txt                                 ← bundled licensed webfont
  .htaccess                                                    ← optional Apache/SiteGround tuning
  audio.m4a                                                    ← only with --audio
```

All paths are relative, so the folder works at a domain root or in any
subfolder. The source video is never copied into it.

## Hosting

Any static host works: upload the **contents** of the folder.

* **SiteGround / cPanel / any Apache host** — step-by-step guide in
  [docs/SITEGROUND.md](docs/SITEGROUND.md). `scripts/package-zip.sh www`
  makes a zip you can upload and extract in Site Tools → File Manager.
* **GitHub Pages** — push the folder's contents to a `gh-pages` branch (or
  publish `www/` with a Pages workflow).
* **Netlify / Cloudflare Pages / S3** — drag-and-drop or sync the folder.

Correct MIME types help but are not required: `.js` → `text/javascript`,
`.json` → `application/json`, `.woff2` → `font/woff2`, `.ascf` →
`application/octet-stream`. The `.htaccess` sets these on Apache.

## Player controls

Controls appear on mouse movement, tap or keyboard focus and fade while
playing. Keyboard: **Space/K** play-pause · **←/→** seek 5 s (**Shift** = one
frame) · **Home** start · **L** loop · **T** colour theme · **F** fullscreen ·
**I** glyph lens/ripples on-off · **M** mute (films with audio). Click or tap
sends a shockwave through the glyphs; on touch screens, drag a finger to move
the lens. Visitors who prefer reduced motion get a paused first frame, a play
button instead of autoplay, and no glyph physics.

## Testing

```bash
scripts/make-fixture.sh                 # synthetic test videos (FFmpeg)
pytest -q                               # 84 Python unit + integration tests
npm test                                # Node decoder + glyph-physics tests
npm install && npm run e2e:install
npm run e2e                             # Playwright: Chromium, Firefox, WebKit
node scripts/profile-player.mjs www     # playback timing at 1920×1080 @2x
```

Measured results are in [docs/REPORT.md](docs/REPORT.md).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ffmpeg and ffprobe not found` | `brew install ffmpeg` (or your distro's package). |
| `output directory … is not empty` | Pass `--force` to replace it (the old folder is removed only after the new one is complete). |
| `font … is not fixed-pitch` | Use a monospaced font, or `--allow-proportional-font` if you really mean it. |
| `no license file found next to font` | Put the font's `LICENSE` beside it or pass `--font-license`. Only ship fonts you may redistribute. |
| Page says *DecompressionStream* is missing | The browser is too old; use current Chrome, Edge, Firefox or Safari (2023+). |
| Blank page when opening `index.html` from disk | Browsers block `fetch` on `file://`. Serve it: `scripts/serve.sh www`. |
| Audio won't seek in local preview | `python -m http.server` lacks HTTP Range; `scripts/serve.sh` supports it, as do real hosts. |
| HTTP 404 for `film.ascf` after upload | Upload the folder's *contents* (and the hidden `.htaccess`); check file names are unchanged. |
| Image looks too dark / flat | Try `ascii-film preview clip.mp4 --time N --png x.png` with `--gamma 0.7`, `--contrast 1.1`, or a bigger glyph set. |
| Large `film.ascf` | Fewer `--columns`, lower `--fps`, or a shorter clip. The whole file downloads before playback in v1. |

## Limitations (v1)

The whole `.ascf` downloads before playback; output is constant frame rate;
monochrome only; requires `DecompressionStream`; Firefox E2E tests could not be
run in the build environment (see the report). Future ideas: HTTP range
streaming, palette colour, GPU encoding, alternate grid sizes, subtitles.

## Licence

Code: MIT ([LICENSE](LICENSE)). Bundled DejaVu fonts: Bitstream Vera / public
domain changes ([assets/fonts/LICENSE-DejaVu.txt](assets/fonts/LICENSE-DejaVu.txt)).
The full design specification this project was built from is in
[build.md](build.md).
