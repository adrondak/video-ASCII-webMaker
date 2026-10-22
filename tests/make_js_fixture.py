"""Write tests/fixtures/tiny.ascf + tiny.expected.json for the Node decoder test.

    python tests/make_js_fixture.py
"""

import json
from pathlib import Path

import numpy as np

from encoder.container import AscfWriter

OUT = Path(__file__).resolve().parent / "fixtures"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    rng = np.random.default_rng(42)
    glyphs = [" ", ".", ":", "o", "O", "@", "é", "▒"]
    rows, cols = 7, 11
    grid = rng.integers(0, len(glyphs), (rows, cols), dtype=np.uint8)
    frames = []
    for i in range(40):
        if i == 20:  # hard change -> keyframe
            grid = rng.integers(0, len(glyphs), (rows, cols), dtype=np.uint8)
        elif i % 3:  # a few cells change; every third frame is identical (empty delta)
            mask = rng.random((rows, cols)) < 0.15
            grid = np.where(mask, rng.integers(0, len(glyphs), (rows, cols)), grid).astype(np.uint8)
        frames.append(grid.copy())
    with AscfWriter(OUT / "tiny.ascf", cols, rows, 30000, 1001, glyphs, keyframe_interval=8) as w:
        kinds = [w.add_frame(f) for f in frames]
    expected = {"columns": cols, "rows": rows, "fps": [30000, 1001], "glyphs": glyphs,
                "kinds": kinds, "frames": [f.ravel().tolist() for f in frames]}
    (OUT / "tiny.expected.json").write_text(json.dumps(expected) + "\n")
    print(f"wrote {OUT / 'tiny.ascf'} ({len(frames)} frames, kinds {kinds})")


if __name__ == "__main__":
    main()
