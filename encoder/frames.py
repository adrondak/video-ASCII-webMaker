"""Decode frames through an FFmpeg subprocess with bounded memory.

Frames are resampled to a constant output frame rate with FFmpeg's ``fps``
filter (this may duplicate or drop source frames) and scaled with area
averaging to the *sampling* resolution. Only one frame is held in memory at a
time; nothing is written to disk.
"""

from __future__ import annotations

import subprocess
import threading
from collections import deque
from collections.abc import Iterator

import numpy as np

from .errors import EncodeError
from .probe import MediaInfo, require_tools


class _StderrTail(threading.Thread):
    """Drain a pipe so FFmpeg never blocks on a full stderr buffer."""

    def __init__(self, pipe, max_lines: int = 40):
        super().__init__(daemon=True)
        self.pipe = pipe
        self.lines: deque[str] = deque(maxlen=max_lines)

    def run(self) -> None:
        for raw in iter(self.pipe.readline, b""):
            self.lines.append(raw.decode("utf-8", "replace").rstrip())

    def text(self) -> str:
        return "\n".join(self.lines).strip()


def iter_rgb_frames(info: MediaInfo, fps: int, width: int, height: int,
                    max_frames: int | None = None, start: float = 0.0) -> Iterator[np.ndarray]:
    """Yield ``(height, width, 3)`` uint8 RGB frames at a constant ``fps``.

    ``start`` seeks (accurately) to that many seconds before decoding.
    """
    ffmpeg, _ = require_tools()
    vf = f"fps={fps},scale={width}:{height}:flags=area,setsar=1,format=rgb24"
    seek = ["-ss", f"{start:.6f}"] if start > 0 else []
    cmd = [ffmpeg, "-v", "error", "-nostdin", *seek, "-i", str(info.path),
           "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", vf,
           "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    frame_bytes = width * height * 3
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            stdin=subprocess.DEVNULL, bufsize=frame_bytes)
    tail = _StderrTail(proc.stderr)
    tail.start()
    count = 0
    finished = False
    try:
        buf = bytearray(frame_bytes)
        view = memoryview(buf)
        while max_frames is None or count < max_frames:
            got = 0
            while got < frame_bytes:
                n = proc.stdout.readinto(view[got:])
                if not n:
                    break
                got += n
            if got == 0:
                finished = True
                break
            if got != frame_bytes:
                raise EncodeError(f"FFmpeg produced a truncated frame ({got}/{frame_bytes} bytes)")
            yield np.frombuffer(buf, dtype=np.uint8).reshape(height, width, 3).copy()
            count += 1
    finally:
        if not finished and proc.poll() is None:
            proc.kill()
        proc.stdout.close()
        rc = proc.wait()
        tail.join(timeout=5)
        if finished and rc != 0:
            raise EncodeError(f"FFmpeg failed decoding {info.path} (exit {rc}): {tail.text()}")
    if count == 0:
        raise EncodeError(f"FFmpeg decoded no frames from {info.path}: {tail.text()}")
