# ASCII Film

Turn a video into a moving image made of **real typographic characters**,
encoded once on your machine and played back by a tiny static Canvas website.

> **Checkpoint 02 — image engine.** On top of the foundation (probing,
> config, fixtures, CFR decoding) this snapshot adds font calibration (glyphs
> sorted by *measured* ink), grid sizing from the measured cell aspect,
> linear-light luminance, tone curve with auto-levels, seeded glyph variation,
> ordered dither, shape-aware detail weighting and temporal stabilisation.
> `ascii-film preview` prints or rasterises a single frame. The binary
> container, packaging and web player arrive in later checkpoints. See
> `build.md` for the full specification.

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
```
