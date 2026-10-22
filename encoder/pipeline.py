"""End-to-end ``encode``: source video -> self-contained static publish directory."""

from __future__ import annotations

import math
import shutil
import sys
import time
from pathlib import Path

from . import __version__
from .config import EncodeConfig
from .container import AscfFile, AscfWriter
from .engine import FrameEngine
from .errors import EncodeError
from .package import (ANIMATION_FILE, AUDIO_FILE, check_disk_space, check_output_path,
                      copy_player, extract_audio, find_font_assets, staged_directory,
                      write_manifest)
from .probe import probe


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return str(n)


class Progress:
    def __init__(self, total: int, stream=sys.stderr):
        self.total = max(total, 1)
        self.stream = stream
        self.start = time.monotonic()
        self.last = 0.0
        self.tty = stream.isatty()

    def update(self, done: int, final: bool = False) -> None:
        now = time.monotonic()
        if not final and now - self.last < (0.25 if self.tty else 2.0):
            return
        self.last = now
        elapsed = now - self.start
        rate = done / elapsed if elapsed > 0 else 0.0
        pct = min(100.0, 100.0 * done / self.total)
        eta = (self.total - done) / rate if rate > 0 and not final else 0.0
        line = f"  frames {done}/{self.total} ({pct:5.1f}%)  {rate:5.1f} fps  eta {eta:4.0f}s"
        if self.tty:
            self.stream.write("\r" + line + ("\n" if final else ""))
        else:
            self.stream.write(line + "\n")
        self.stream.flush()


def encode(cfg: EncodeConfig, source: str | Path, output: str | Path, force: bool = False,
           log=print) -> dict:
    """Encode ``source`` into a publish directory at ``output``; return a summary."""
    t0 = time.monotonic()
    source, output = Path(source), Path(output)
    info = probe(source)
    log(f"source:   {info.describe()}")
    check_output_path(output, source, force)

    engine = FrameEngine(cfg, info)
    if engine.grid_warning:
        log(f"warning: {engine.grid_warning}")
    m = engine.glyphs.metrics
    webfont, font_license = find_font_assets(Path(cfg.font), cfg.font_license)
    est_frames = min(math.ceil(info.duration * cfg.fps), cfg.max_frames)
    cells = engine.columns * engine.rows
    log(f"grid:     {engine.columns} x {engine.rows} cells "
        f"({m.family} {m.cell_width:.2f} x {m.cell_height:.2f} px @ {m.size:g}px), "
        f"{len(engine.glyphs)} glyphs")
    log(f"workload: ~{est_frames} frames at {cfg.fps} fps "
        f"(~{est_frames * cells / 1e6:.1f} M cells); sampling "
        f"{engine.sample_size[0]}x{engine.sample_size[1]} px per frame")
    if info.duration * cfg.fps > cfg.max_frames:
        log(f"warning: source is longer than max_frames={cfg.max_frames}; output is truncated")
    check_disk_space(output.parent if output.parent != Path("") else Path("."),
                     est_frames * (cells + 64) + 64 * 1024 * 1024)

    with staged_directory(output, force) as staging:
        levels = engine.measure_levels()
        if cfg.auto_levels:
            log(f"levels:   tone {levels[0]:.3f} .. {levels[1]:.3f} (auto)")
        progress = Progress(est_frames)
        with AscfWriter(staging / ANIMATION_FILE, engine.columns, engine.rows, cfg.fps, 1,
                        engine.glyphs.chars, cfg.keyframe_interval) as writer:
            for grid in engine.grids():
                writer.add_frame(grid)
                progress.update(writer.stats.frames)
        progress.update(writer.stats.frames, final=True)
        stats = writer.stats
        duration = stats.frames / cfg.fps

        # Re-read and fully validate what we wrote before publishing it.
        check = AscfFile.open(staging / ANIMATION_FILE)
        check.validate_all()
        if not check.timestamps_exact():
            raise EncodeError("internal error: written timestamps are not exact")

        audio_name = None
        audio_offset = 0.0
        if info.has_audio and cfg.audio:
            audio_offset = extract_audio(info, staging / AUDIO_FILE, duration, cfg.audio_bitrate)
            audio_name = AUDIO_FILE
        elif info.has_audio:
            log("audio:    not included (pass --audio to package the soundtrack)")
        else:
            log("audio:    source has no audio stream")

        font_file = "font" + webfont.suffix
        shutil.copyfile(webfont, staging / font_file)
        shutil.copyfile(font_license, staging / "FONT-LICENSE.txt")
        copy_player(staging)
        manifest = {
            "schemaVersion": 1,
            "title": cfg.title,
            "description": cfg.description,
            "animation": ANIMATION_FILE,
            "audio": audio_name,
            "audioOffsetSeconds": audio_offset,
            "durationSeconds": round(duration, 6),
            "fps": {"numerator": cfg.fps, "denominator": 1},
            "columns": engine.columns,
            "rows": engine.rows,
            "frameCount": stats.frames,
            "font": {
                "family": m.family,
                "file": font_file,
                "license": "FONT-LICENSE.txt",
                "size": m.size,
                "cellWidth": round(m.cell_width, 4),
                "cellHeight": round(m.cell_height, 4),
                "ascent": round(m.ascent_em, 6),
                "descent": round(m.descent_em, 6),
                "lineHeight": round(m.line_height_em, 6),
            },
            "theme": {"foreground": cfg.foreground, "background": cfg.background},
            "loop": cfg.loop,
            "autoplay": cfg.autoplay,
            "generator": f"ascii-film {__version__}",
            "encoding": {
                "glyphs": "".join(engine.glyphs.chars),
                "levels": list(levels),
                "brightness": cfg.brightness, "contrast": cfg.contrast, "gamma": cfg.gamma,
                "invert": cfg.invert, "detail": cfg.detail, "dither": cfg.dither,
                "variation": cfg.variation, "seed": cfg.seed,
                "stability": cfg.stability if cfg.stabilization else 0.0,
                "keyframeInterval": cfg.keyframe_interval,
                "sourceFrameRate": str(info.frame_rate) if info.frame_rate else None,
                "resampledToFps": cfg.fps,
            },
        }
        write_manifest(staging, manifest)
        total = sum(f.stat().st_size for f in staging.iterdir() if f.is_file())

    elapsed = time.monotonic() - t0
    summary = {
        "output": str(output), "frames": stats.frames, "keyframes": stats.keyframes,
        "deltas": stats.deltas, "duration": duration, "columns": engine.columns,
        "rows": engine.rows, "animation_bytes": stats.total_bytes, "total_bytes": total,
        "audio": audio_name is not None, "cuts": engine.stats.cuts, "elapsed": elapsed,
    }
    log(f"frames:   {stats.frames} ({stats.keyframes} key / {stats.deltas} delta), "
        f"{duration:.3f}s, {engine.stats.cuts} hard cut(s) detected")
    log(f"output:   {output}/ — animation {_human(stats.total_bytes)}, "
        f"total {_human(total)}, in {elapsed:.1f}s")
    log(f"preview:  python3 -m http.server 8000 --directory {output}  ->  http://localhost:8000/")
    return summary
