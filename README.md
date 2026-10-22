# ASCII Film

Turn a video into a moving image made of **real typographic characters**,
encoded once on your machine and played back by a tiny static Canvas website.

> **Checkpoint 05 — full web player.** Replaces the minimal player with a
> glyph-atlas Canvas renderer (integer device-pixel cells, partial redraw of
> changed cells, HiDPI), a performance.now()/audio master clock that skips
> late frames, controls (play/pause, scrub, time, mute/volume, loop, colour
> theme, fullscreen), keyboard shortcuts, reduced-motion handling, loading
> and error states, and a Playwright suite for Chromium, Firefox and WebKit.

## Setup (macOS)

```bash
brew install ffmpeg python@3.13 node
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock && pip install -e . --no-deps
scripts/make-fixture.sh            # synthetic test videos in tests/fixtures/
pytest -q
```

## Try it

```bash
ascii-film probe tests/fixtures/landscape.mp4
ascii-film preview tests/fixtures/landscape.mp4 --time 1 --columns 100
ascii-film preview your-clip.mp4 --time 5 --detail 1 --png frame.png
ascii-film encode tests/fixtures/landscape.mp4 --output dist/landscape
ascii-film inspect dist/landscape/film.ascf
scripts/serve.sh dist/landscape        # open http://localhost:8000/  (Range-capable server)
npm test                               # Node decoder tests
npm install && npm run e2e:install && npm run e2e   # browser end-to-end tests
```

Keyboard: Space/K play-pause, ←/→ seek 5 s (Shift = one frame), Home, M mute,
L loop, T colour theme, F fullscreen.
