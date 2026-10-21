"""Locate FFmpeg and inspect source media with ffprobe."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from .errors import EncodeError


def require_tools() -> tuple[str, str]:
    """Return absolute paths of ffmpeg and ffprobe or raise a helpful error."""
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    missing = [name for name, path in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)) if not path]
    if missing:
        raise EncodeError(
            f"{' and '.join(missing)} not found on PATH. Install FFmpeg "
            "(macOS: `brew install ffmpeg`) and try again."
        )
    return ffmpeg, ffprobe  # type: ignore[return-value]


@dataclass(frozen=True)
class MediaInfo:
    path: Path
    coded_width: int
    coded_height: int
    width: int  # display width after sample aspect ratio and rotation
    height: int  # display height after sample aspect ratio and rotation
    rotation: int  # degrees, normalised to 0/90/180/270
    sample_aspect: Fraction
    frame_rate: Fraction | None
    duration: float
    video_codec: str
    video_start: float
    has_audio: bool
    audio_codec: str | None
    audio_start: float
    audio_channels: int

    def describe(self) -> str:
        fr = f"{float(self.frame_rate):.3f} fps" if self.frame_rate else "unknown fps"
        rot = f", rotated {self.rotation}°" if self.rotation else ""
        sar = f", SAR {self.sample_aspect}" if self.sample_aspect != 1 else ""
        audio = (f"{self.audio_codec} audio ({self.audio_channels} ch)" if self.has_audio
                 else "no audio")
        return (f"{self.path.name}: {self.video_codec} {self.coded_width}x{self.coded_height}"
                f"{sar}{rot} -> display {self.width}x{self.height}, {fr}, "
                f"{self.duration:.3f}s, {audio}")


def _fraction(text: str | None) -> Fraction | None:
    if not text or text in ("0/0", "N/A"):
        return None
    try:
        value = Fraction(text.replace(":", "/"))
    except (ValueError, ZeroDivisionError):
        return None
    return value if value > 0 else None


def _float(text, default: float = 0.0) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def _rotation(stream: dict) -> int:
    rot = 0.0
    for side in stream.get("side_data_list", []) or []:
        if "rotation" in side:
            rot = _float(side["rotation"])
            break
    else:
        rot = _float((stream.get("tags") or {}).get("rotate"))
    return int(round(rot)) % 360 // 90 * 90


def probe(path: str | Path) -> MediaInfo:
    src = Path(path)
    if not src.is_file():
        raise EncodeError(f"source file not found: {src}")
    _, ffprobe = require_tools()
    cmd = [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
           str(src)]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=60, check=False)
    except subprocess.TimeoutExpired:
        raise EncodeError(f"ffprobe timed out reading {src}") from None
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip() or "unknown error"
        raise EncodeError(f"ffprobe could not read {src}: {detail}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise EncodeError(f"ffprobe returned unreadable output for {src}") from None

    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not (s.get("disposition") or {}).get("attached_pic")), None)
    if video is None:
        raise EncodeError(f"{src} has no decodable video stream (unsupported file?)")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    cw, ch = int(video.get("width") or 0), int(video.get("height") or 0)
    if cw <= 0 or ch <= 0:
        raise EncodeError(f"{src}: video stream has no valid dimensions")
    sar = _fraction(video.get("sample_aspect_ratio")) or Fraction(1)
    rotation = _rotation(video)
    w = max(1, round(cw * sar))
    h = ch
    if rotation in (90, 270):
        w, h = h, w

    fmt = data.get("format", {})
    duration = _float(fmt.get("duration")) or _float(video.get("duration"))
    if duration <= 0:
        raise EncodeError(f"{src} reports zero or unknown duration")

    frame_rate = _fraction(video.get("avg_frame_rate")) or _fraction(video.get("r_frame_rate"))
    return MediaInfo(
        path=src,
        coded_width=cw,
        coded_height=ch,
        width=w,
        height=h,
        rotation=rotation,
        sample_aspect=sar,
        frame_rate=frame_rate,
        duration=duration,
        video_codec=str(video.get("codec_name", "unknown")),
        video_start=_float(video.get("start_time")),
        has_audio=audio is not None,
        audio_codec=str(audio.get("codec_name")) if audio else None,
        audio_start=_float(audio.get("start_time")) if audio else 0.0,
        audio_channels=int(audio.get("channels") or 0) if audio else 0,
    )
