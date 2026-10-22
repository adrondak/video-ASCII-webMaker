# ASCII Film

Turn a video into a moving image made of **real typographic characters**,
encoded once on your machine and played back by a tiny static Canvas website.

> **Checkpoint 03 — container.** Adds the ASCF v1 binary format (see
> `encoder/container.py` and `build.md` §6): periodic zlib keyframes, delta
> frames chosen only when smaller after compression, an exact rational
> timestamp index, a validating reader with seeking, and `ascii-film inspect`.
> `encode` here writes a bare `.ascf`; packaging and the web player come next.

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
ascii-film encode tests/fixtures/landscape.mp4 --output landscape.ascf
ascii-film inspect landscape.ascf
```
