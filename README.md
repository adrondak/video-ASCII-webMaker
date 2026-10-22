# ASCII Film

Turn a video into a moving image made of **real typographic characters**,
encoded once on your machine and played back by a tiny static Canvas website.

> **Checkpoint 06 — hardening.** Adds a seamless-loop option
> (`loop_crossfade`: the ending dissolves into the opening in linear light,
> and the stabiliser is spliced so the loop point never shimmers), a playback
> profiler (`node scripts/profile-player.mjs <dir>`), a backlog fix for the
> preview server, and more tests. The next checkpoint adds the finished
> `www/` site and full documentation.

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
