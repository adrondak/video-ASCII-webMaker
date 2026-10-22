"""Command-line entry point: ``ascii-film``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import build_config
from .engine import FrameEngine
from .errors import EncodeError
from .glyphs import render_grid_image
from .mapping import grid_to_text
from .probe import probe

EPILOG = """examples:
  ascii-film probe clip.mp4
  ascii-film preview clip.mp4 --time 3.5 --columns 120
"""


def _add_render_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("source", help="input video (MP4, MOV, ...)")
    p.add_argument("--config", help="JSON config file (CLI flags override it)")
    g = p.add_argument_group("geometry and timing")
    g.add_argument("--fps", type=int, help="output frame rate, 1-60 (default 24)")
    g.add_argument("--columns", type=int, help="character columns, 40-320 (default 160)")
    g.add_argument("--font", help="monospaced TTF/OTF used for calibration (default DejaVu Sans Mono)")
    g.add_argument("--font-size", type=float, help="reference font size in px (default 20)")
    g.add_argument("--line-height", type=float, help="line height in em (default: font metrics)")
    g.add_argument("--allow-proportional-font", action="store_true", default=None)
    g = p.add_argument_group("tone and glyphs")
    g.add_argument("--glyphs", help="candidate glyphs; sorted by measured ink, not by order")
    g.add_argument("--brightness", type=float, help="-1..1 (default 0)")
    g.add_argument("--contrast", type=float, help="0.1..5 (default 1.0)")
    g.add_argument("--gamma", type=float, help="0.1..5 (default 1.0)")
    g.add_argument("--no-auto-levels", dest="auto_levels", action="store_false", default=None,
                   help="disable the global auto-levels pre-pass")
    g.add_argument("--invert", action="store_true", default=None, help="reverse polarity")
    g.add_argument("--detail", type=float, help="edge/shape weighting 0..4 (default 0 = off)")
    g.add_argument("--dither", type=float, help="ordered dither strength 0..2 (default 0)")
    g.add_argument("--variation", type=float, help="seeded per-cell glyph variation 0..2 (default 0.35)")
    g.add_argument("--seed", type=int, help="seed for the variation pattern (default 1)")
    g.add_argument("--foreground", help="#rrggbb glyph color (default #eeeeee)")
    g.add_argument("--background", help="#rrggbb background (default #101010)")
    g = p.add_argument_group("temporal")
    g.add_argument("--stability", type=float, help="0..1 (default 0.25)")
    g.add_argument("--no-stabilization", dest="stabilization", action="store_false", default=None)
    g.add_argument("--cut-threshold", type=float, help="hard-cut detector threshold (default 0.22)")
    g.add_argument("--cut", dest="scene_cuts", type=float, action="append",
                   help="explicit scene boundary in seconds (repeatable)")


OPTION_NAMES = ["fps", "columns", "font", "font_size", "line_height", "allow_proportional_font",
                "glyphs", "brightness", "contrast", "gamma", "auto_levels", "invert", "detail",
                "dither", "variation", "seed", "foreground", "background", "stability",
                "stabilization", "cut_threshold", "scene_cuts"]


def _overrides(args: argparse.Namespace) -> dict:
    return {name: getattr(args, name, None) for name in OPTION_NAMES}


def _config(args: argparse.Namespace):
    cfg, warnings = build_config(args.config, _overrides(args))
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    return cfg


def cmd_probe(args: argparse.Namespace) -> int:
    print(probe(args.source).describe())
    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    """Render one frame as plain text — a debugging aid, not a publish format."""
    cfg = _config(args)
    info = probe(args.source)
    engine = FrameEngine(cfg, info)
    if engine.grid_warning:
        print(f"warning: {engine.grid_warning}", file=sys.stderr)
    engine.measure_levels()
    t = min(max(args.time, 0.0), max(info.duration - 1.0 / cfg.fps, 0.0))
    grid = next(engine.grids(max_frames=1, start=t))
    text = grid_to_text(grid, engine.glyphs.chars)
    if args.png:
        render_grid_image(grid, engine.glyphs, cfg.foreground, cfg.background).save(args.png)
        print(f"wrote {args.png}", file=sys.stderr)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {engine.columns}x{engine.rows} preview of t={t:.2f}s to {args.output}",
              file=sys.stderr)
    elif not args.png:
        print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ascii-film",
        description="Turn a video into a moving image made of typographic characters.",
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"ascii-film {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("probe", help="print what ffprobe reports about a source")
    p.add_argument("source")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("preview", help="print one frame as ASCII text (debugging aid)")
    _add_render_options(p)
    p.add_argument("--time", type=float, default=0.0, help="timestamp in seconds (default 0)")
    p.add_argument("--output", "-o", help="write the text to a file instead of stdout")
    p.add_argument("--png", help="also rasterise the frame with the font to this PNG")
    p.set_defaults(func=cmd_preview)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except EncodeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
