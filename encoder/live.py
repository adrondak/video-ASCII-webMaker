"""Build the live webcam site: ``ascii-film live --output www-live``.

There is no source video and no .ascf: the visitor's browser maps camera
frames to glyphs in real time (web/camera.js). This command calibrates the
font with the same code the film encoder uses and writes everything the page
needs into ``live.json``, next to the player files, font and licence.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import __version__
from .config import EncodeConfig
from .errors import EncodeError
from .glyphs import calibrate
from .mapping import ink_is_light
from .package import WEB_DIR, find_font_assets, staged_directory

LIVE_FILES = {
    "live.html": "index.html",
    "live.js": "live.js",
    "camera.js": "camera.js",
    "renderer.js": "renderer.js",
    "field.js": "field.js",
    "pointer.js": "pointer.js",
    "player.css": "player.css",
    ".htaccess": ".htaccess",
}
LIVE_COLUMN_STEPS = [80, 100, 120, 140, 160, 190, 220]


def check_live_output(output: Path, force: bool) -> None:
    out = output.resolve()
    if out.exists() and not out.is_dir():
        raise EncodeError(f"output {out} exists and is not a directory")
    if out.exists() and any(out.iterdir()) and not force:
        raise EncodeError(f"output directory {out} is not empty; pass --force to replace it")
    if (out / "film.ascf").exists():
        raise EncodeError(f"{out} holds an encoded film; keep the live site in its own folder")


def build_live(cfg: EncodeConfig, output: str | Path, force: bool = False, log=print) -> dict:
    output = Path(output)
    check_live_output(output, force)
    glyphs = calibrate(cfg.font, cfg.glyphs, cfg.font_size, cfg.line_height,
                       (cfg.oversample_y, cfg.oversample_x), cfg.allow_proportional_font)
    m = glyphs.metrics
    webfont, font_license = find_font_assets(Path(cfg.font), cfg.font_license)
    steps = sorted(set(LIVE_COLUMN_STEPS) | {cfg.columns})
    manifest = {
        "schemaVersion": 1,
        "kind": "live",
        "title": cfg.title,
        "description": cfg.description,
        "columns": cfg.columns,
        "columnSteps": steps,
        "font": {
            "family": m.family,
            "file": "font" + webfont.suffix,
            "license": "FONT-LICENSE.txt",
            "size": m.size,
            "cellWidth": round(m.cell_width, 4),
            "cellHeight": round(m.cell_height, 4),
            "ascent": round(m.ascent_em, 6),
            "descent": round(m.descent_em, 6),
            "lineHeight": round(m.line_height_em, 6),
        },
        "glyphs": glyphs.chars,
        "coverage": [round(float(c), 6) for c in glyphs.coverage],
        "theme": {"foreground": cfg.foreground, "background": cfg.background},
        "mapping": {
            "inkLight": ink_is_light(cfg.foreground, cfg.background),
            "oversampleX": cfg.oversample_x,
            "oversampleY": cfg.oversample_y,
            "brightness": cfg.brightness,
            "contrast": cfg.contrast,
            "gamma": cfg.gamma,
            "invert": cfg.invert,
            "autoLevels": cfg.auto_levels,
            "levelsLowPercentile": cfg.levels_low_percentile,
            "levelsHighPercentile": cfg.levels_high_percentile,
            "variation": cfg.variation,
            "dither": cfg.dither,
            "seed": cfg.seed,
            "stability": cfg.stability if cfg.stabilization else 0.0,
            "cutThreshold": cfg.cut_threshold,
        },
        "interaction": {
            "lens": cfg.lens, "lensRadius": cfg.lens_radius,
            "lensStrength": cfg.lens_strength, "ripples": cfg.ripples,
            "rippleStrength": cfg.ripple_strength,
        },
        "generator": f"ascii-film {__version__}",
    }
    with staged_directory(output, force) as staging:
        for src, dest in LIVE_FILES.items():
            path = WEB_DIR / src
            if not path.exists():
                raise EncodeError(f"live page file missing from the project: {path}")
            shutil.copyfile(path, staging / dest)
        shutil.copyfile(webfont, staging / manifest["font"]["file"])
        shutil.copyfile(font_license, staging / "FONT-LICENSE.txt")
        (staging / "live.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                           encoding="utf-8")
        total = sum(f.stat().st_size for f in staging.iterdir() if f.is_file())
    log(f"live:     {output}/ — {len(glyphs)} glyphs, {cfg.columns} columns by default, "
        f"{total / 1024:.0f} KB total")
    log(f"preview:  scripts/serve.sh {output}  ->  http://localhost:8000/  "
        "(camera needs https or localhost)")
    return {"output": str(output), "glyphs": len(glyphs), "bytes": total}
