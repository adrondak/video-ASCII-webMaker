"""Command-line entry point: ``ascii-film``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import build_config
from .container import AscfFile
from .engine import FrameEngine
from .pipeline import encode
from .errors import AscfError, EncodeError
from .glyphs import render_grid_image
from .mapping import grid_to_text
from .probe import probe

EPILOG = """examples:
  ascii-film probe clip.mp4
  ascii-film encode clip.mp4 --output dist/my-film --config examples/demo-config.json
  ascii-film encode clip.mp4 -o www --columns 200 --title "Ocean" --force
  ascii-film inspect film.ascf
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
                "stabilization", "cut_threshold", "scene_cuts", "title", "description",
                "keyframe_interval", "audio", "autoplay", "loop", "font_license", "max_frames",
                "loop_crossfade", "lens", "ripples", "lens_radius", "lens_strength",
                "ripple_strength"]


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


def cmd_encode(args: argparse.Namespace) -> int:
    cfg = _config(args)
    encode(cfg, args.source, args.output, force=args.force,
           log=lambda msg: print(msg, file=sys.stderr))
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    try:
        f = AscfFile.open(args.file)
        summary = f.validate_all()
    except (AscfError, OSError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    h = f.header
    sizes = f.index["clen"].astype(int)
    print(f"file:            {args.file}")
    print(f"format:          ASCF v{h.version[0]}.{h.version[1]}, {h.total_bytes} bytes")
    print(f"grid:            {h.columns} x {h.rows} ({h.columns * h.rows} cells)")
    print(f"frames:          {h.frame_count} at {h.fps_num}/{h.fps_den} fps "
          f"= {h.duration_us / 1e6:.3f} s")
    print(f"keyframes:       {summary['keyframes']} (interval {h.keyframe_interval}), "
          f"deltas: {summary['deltas']}")
    print(f"payload bytes:   min {sizes.min()}, mean {sizes.mean():.0f}, max {sizes.max()}")
    print(f"glyphs ({len(f.glyphs):3d}):    {''.join(f.glyphs)!r}")
    print(f"timestamps:      {'exact CFR, monotonic' if f.timestamps_exact() else 'monotonic'}")
    print("integrity:       OK (structure + zlib Adler-32; ASCF v1 has no extra checksums)")
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

    p = sub.add_parser("encode", help="encode a video into a static publish directory",
                       epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    _add_render_options(p)
    p.add_argument("--output", "-o", required=True, help="publish directory to create")
    p.add_argument("--force", action="store_true", help="replace an existing output directory")
    g = p.add_argument_group("package")
    g.add_argument("--title", help="film title (shown in the browser tab)")
    g.add_argument("--description", help="alt text describing the film for screen readers")
    g.add_argument("--keyframe-interval", type=int, help="max frames between keyframes (default 48)")
    g.add_argument("--audio", dest="audio", action="store_true", default=None,
                   help="include the source soundtrack as AAC audio.m4a (off by default)")
    g.add_argument("--no-audio", dest="audio", action="store_false")
    g.add_argument("--autoplay", choices=["muted", "off"],
                   help="'muted' starts playing on load (default); 'off' waits for a click")
    g.add_argument("--no-loop", dest="loop", action="store_false", default=None)
    g.add_argument("--loop-crossfade", type=float,
                   help="seconds of the ending dissolved into the opening for a seamless loop")
    g.add_argument("--font-license", help="license file to ship with the font")
    g.add_argument("--no-lens", dest="lens", action="store_false", default=None,
                   help="disable the cursor lens that parts and magnifies glyphs")
    g.add_argument("--no-ripples", dest="ripples", action="store_false", default=None,
                   help="disable ripples sent through the glyphs by cursor movement")
    g.add_argument("--lens-radius", type=float, help="lens radius in cell widths (default 7)")
    g.add_argument("--lens-strength", type=float,
                   help="lens push/magnification 0..2.2 (default 1.4)")
    g.add_argument("--ripple-strength", type=float, help="ripple push/swell multiplier 0..4 (default 1)")
    g.add_argument("--max-frames", type=int, help="stop after this many frames")
    p.set_defaults(func=cmd_encode)

    p = sub.add_parser("inspect", help="validate an .ascf file and print its structure")
    p.add_argument("file")
    p.set_defaults(func=cmd_inspect)
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
