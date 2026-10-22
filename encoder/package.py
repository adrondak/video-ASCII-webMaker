"""Build the static publish directory: animation, manifest, audio, font, player.

Output is written into a hidden staging directory next to the destination and
renamed into place only after everything succeeded, so a failed or interrupted
encode never leaves a half-published directory behind.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .config import REPO_ROOT
from .errors import EncodeError
from .probe import MediaInfo, require_tools

WEB_DIR = REPO_ROOT / "web"
WEB_FILES = ["index.html", "player.css", "player.js", "decoder.js", "renderer.js", "field.js",
             ".htaccess"]
ANIMATION_FILE = "film.ascf"
AUDIO_FILE = "audio.m4a"
MANIFEST_FILE = "manifest.json"


def check_output_path(output: Path, source: Path, force: bool) -> None:
    out = output.resolve()
    src = source.resolve()
    forbidden = {Path("/").resolve(), Path.home().resolve(), REPO_ROOT.resolve(), Path.cwd().resolve()}
    if out in forbidden:
        raise EncodeError(f"refusing to use {out} as an output directory; pick a subdirectory")
    if out == src or out in src.parents:
        raise EncodeError("the output directory must not contain the source video")
    if out in (REPO_ROOT / p for p in ("encoder", "web", "assets", "tests", "scripts")):
        raise EncodeError(f"refusing to overwrite project directory {out}")
    if out.exists() and not out.is_dir():
        raise EncodeError(f"output {out} exists and is not a directory")
    if out.exists() and any(out.iterdir()) and not force:
        raise EncodeError(f"output directory {out} is not empty; pass --force to replace it")


def check_disk_space(directory: Path, needed_bytes: int) -> None:
    probe_dir = directory
    while not probe_dir.exists():
        probe_dir = probe_dir.parent
    free = shutil.disk_usage(probe_dir).free
    if free < needed_bytes:
        raise EncodeError(f"insufficient disk space in {probe_dir}: need ~{needed_bytes >> 20} MiB, "
                          f"have {free >> 20} MiB")


@contextmanager
def staged_directory(output: Path, force: bool) -> Iterator[Path]:
    """Yield an empty staging dir; atomically move it to ``output`` on success."""
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.parent / f".{output.name}.staging-{os.getpid()}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    try:
        yield staging
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    old = None
    if output.exists():
        if any(output.iterdir()) and not force:
            shutil.rmtree(staging, ignore_errors=True)
            raise EncodeError(f"{output} appeared during encoding; pass --force to replace it")
        old = output.parent / f".{output.name}.old-{os.getpid()}"
        os.replace(output, old)
    os.replace(staging, output)
    if old is not None:
        shutil.rmtree(old, ignore_errors=True)


def find_font_assets(font_path: Path, license_override: str = "") -> tuple[Path, Path]:
    """Return (webfont file to ship, license file to ship) for a calibration font."""
    woff2 = font_path.with_suffix(".woff2")
    webfont = woff2 if woff2.exists() else font_path
    if license_override:
        lic = Path(license_override)
        if not lic.is_file():
            raise EncodeError(f"font license file not found: {lic}")
        return webfont, lic
    stem = font_path.stem.split("-")[0]
    candidates = sorted(font_path.parent.glob(f"{font_path.stem}.LICENSE*")) + \
        sorted(font_path.parent.glob("LICENSE*")) + sorted(font_path.parent.glob(f"*{stem}*LICENSE*"))
    for lic in candidates:
        if lic.is_file():
            return webfont, lic
    raise EncodeError(f"no license file found next to font {font_path}. Fonts are copied into "
                      "the publish directory, so add its LICENSE (or pass --font-license) and "
                      "make sure it may be redistributed")


def extract_audio(info: MediaInfo, dest: Path, duration: float, bitrate: str) -> float:
    """Transcode the first audio stream to AAC-LC/M4A aligned to animation t=0.

    Returns the applied offset in seconds (positive = audio delayed).
    """
    ffmpeg, _ = require_tools()
    offset = info.audio_start - info.video_start
    filters = []
    if offset > 0.0005:
        filters.append(f"adelay=delays={round(offset * 1000)}:all=1")
    elif offset < -0.0005:
        filters.append(f"atrim=start={-offset:.6f},asetpts=PTS-STARTPTS")
    filters.append("apad")  # pad short audio so the track spans the whole animation
    cmd = [ffmpeg, "-v", "error", "-nostdin", "-y", "-i", str(info.path),
           "-map", "0:a:0", "-vn", "-sn", "-dn", "-af", ",".join(filters),
           "-t", f"{duration:.6f}", "-c:a", "aac", "-profile:a", "aac_low", "-b:a", bitrate,
           "-ac", "2", "-ar", "48000", "-map_metadata", "-1", "-map_chapters", "-1",
           "-fflags", "+bitexact", "-flags:a", "+bitexact", "-movflags", "+faststart",
           str(dest)]
    result = subprocess.run(cmd, capture_output=True, check=False)
    if result.returncode != 0 or not dest.exists():
        raise EncodeError("FFmpeg failed to extract audio: "
                          + result.stderr.decode("utf-8", "replace").strip())
    return round(offset, 6)


def copy_player(staging: Path) -> None:
    for name in WEB_FILES:
        src = WEB_DIR / name
        if not src.exists():
            raise EncodeError(f"player file missing from the project: {src}")
        shutil.copyfile(src, staging / name)


def write_manifest(staging: Path, manifest: dict) -> None:
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    (staging / MANIFEST_FILE).write_text(text, encoding="utf-8")
