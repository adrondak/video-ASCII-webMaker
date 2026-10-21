# ASCII Film

Turn a video into a moving image made of **real typographic characters**,
encoded once on your machine and played back by a tiny static Canvas website.

> **Checkpoint 01 — foundation.** This snapshot has the project skeleton,
> pinned environment, bundled licensed font, FFmpeg probing, configuration
> validation, synthetic fixtures and constant-frame-rate frame decoding.
> Later checkpoints add the glyph engine, the ASCF container, packaging and the
> web player. See `build.md` for the full specification.

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
ascii-film encode tests/fixtures/landscape.mp4 --dry-run   # decode every frame
```
