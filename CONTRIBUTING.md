# Contributing

Thanks for poking at this! Issues and pull requests are welcome — bug
reports, new looks, better glyph matching, ports of the player, anything.

## Set up

```bash
brew install ffmpeg python@3.13 node            # or your distro's packages
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock && pip install -e . --no-deps
npm ci && npx playwright install chromium firefox webkit
```

## Run the tests

```bash
pytest -q          # encoder: unit + end-to-end encodes of synthetic clips
npm test           # player: ASCF decoder + glyph physics (Node, no browser)
npm run e2e        # player in real browsers (Playwright)
```

CI runs all three on every push and pull request.

## Where things live

| Path | What |
|---|---|
| `encoder/` | Python encoder: `probe` → `frames` → `glyphs`/`mapping` → `temporal` → `container` → `package`, glued by `engine.py` and `pipeline.py`. |
| `web/` | The player copied into every publish folder: `decoder.js` (ASCF), `renderer.js` (glyph atlas), `field.js` (lens/ripple physics), `player.js` (clock, controls). No dependencies, no build step. |
| `www/` | The demo site, rebuilt with `ascii-film encode assets/video/1080ocean.mp4 --config examples/ocean-config.json -o www --force`. |
| `docs/ASCF.md` | The binary format. Change it only with a version bump. |
| `tests/` | Python tests, Node tests, Playwright specs in `tests/e2e/`. |

## Guidelines

* Keep the player dependency-free and the site static — it must keep working
  on plain shared hosting.
* Encoding must stay deterministic: same input + settings → identical
  `film.ascf` (there is a test).
* Never ship source video in a publish folder.
* Match the surrounding code style; add a test with each behaviour change.
