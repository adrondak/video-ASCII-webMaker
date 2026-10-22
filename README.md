# ASCII Film

Turn a video into a moving image made of **real typographic characters**,
encoded once on your machine and played back by a tiny static Canvas website.

> **Checkpoint 04 — packaging + minimal player.** `ascii-film encode` now
> builds a complete static publish directory: `film.ascf`, `manifest.json`,
> the bundled licensed webfont, an `.htaccess` for Apache/SiteGround, and a
> deliberately minimal player (one `fillText` per row on a wall clock) to show
> the smallest thing that works. Output is staged and renamed atomically.
> Audio is opt-in (`--audio`). Checkpoint 05 replaces the player with the
> full atlas renderer and controls.

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
python3 -m http.server 8000 --directory dist/landscape   # open http://localhost:8000/
npm test                                                  # Node decoder tests
```
