"""Command-line entry point: ``ascii-film``."""

from __future__ import annotations

import argparse
import math
import sys
import time

from . import __version__
from .config import build_config
from .errors import EncodeError
from .frames import iter_rgb_frames
from .probe import probe

EPILOG = """examples:
  ascii-film probe clip.mp4
  ascii-film encode clip.mp4 --output dist/my-film --dry-run
"""


def _add_encode_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("source", help="input video (MP4, MOV, ...)")
    p.add_argument("--output", "-o", help="publish directory to create")
    p.add_argument("--config", help="JSON config file (CLI flags override it)")
    p.add_argument("--fps", type=int, help="output frame rate, 1-60 (default 24)")
    p.add_argument("--columns", type=int, help="character columns, 40-320 (default 160)")
    p.add_argument("--dry-run", action="store_true",
                   help="probe and decode every frame without writing output")


def _overrides(args: argparse.Namespace) -> dict:
    return {"fps": args.fps, "columns": args.columns}


def cmd_probe(args: argparse.Namespace) -> int:
    print(probe(args.source).describe())
    return 0


def cmd_encode(args: argparse.Namespace) -> int:
    cfg, warnings = build_config(args.config, _overrides(args))
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    info = probe(args.source)
    print(info.describe())
    est = math.ceil(info.duration * cfg.fps)
    print(f"estimated frames: {est} at {cfg.fps} fps")
    start = time.monotonic()
    count = 0
    for _ in iter_rgb_frames(info, cfg.fps, cfg.columns * cfg.oversample_x,
                             cfg.columns * cfg.oversample_y // 2, cfg.max_frames):
        count += 1
    print(f"decoded {count} frames in {time.monotonic() - start:.1f}s")
    if not args.dry_run:
        print("encoding is implemented in a later checkpoint; this build only probes and decodes",
              file=sys.stderr)
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

    p = sub.add_parser("encode", help="encode a video into a publish directory")
    _add_encode_options(p)
    p.set_defaults(func=cmd_encode)
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
