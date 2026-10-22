"""Encoder configuration: defaults, JSON config files, CLI overrides, validation.

Precedence is defaults < JSON config file < CLI flags. JSON keys use the same
names as the dataclass fields (``snake_case``); ``kebab-case`` is accepted too.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from .errors import ConfigError

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FONT = REPO_ROOT / "assets" / "fonts" / "DejaVuSansMono.ttf"
DEFAULT_GLYPHS = " .,:;irsXA253hMHGS#9B&@"

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass
class EncodeConfig:
    # Timing and geometry
    fps: int = 24
    columns: int = 160
    min_rows: int = 20
    max_rows: int = 240
    oversample_x: int = 4
    oversample_y: int = 8
    max_frames: int = 20000

    # Font and glyphs
    font: str = str(DEFAULT_FONT)
    font_size: float = 20.0
    line_height: float | None = None  # in em; None = font ascent + descent
    glyphs: str = DEFAULT_GLYPHS
    allow_proportional_font: bool = False

    # Tone
    brightness: float = 0.0
    contrast: float = 1.0
    gamma: float = 1.0
    auto_levels: bool = True
    levels_low_percentile: float = 0.5
    levels_high_percentile: float = 99.5
    invert: bool = False

    # Glyph choice
    detail: float = 0.0  # edge/shape weighting; 0 = pure tonal match
    dither: float = 0.0  # ordered (Bayer 4x4) dither strength
    variation: float = 0.35  # static seeded per-cell variation
    seed: int = 1

    # Temporal
    stability: float = 0.25
    stabilization: bool = True
    cut_threshold: float = 0.22
    scene_cuts: list[float] = field(default_factory=list)  # explicit boundaries, seconds

    # Container
    keyframe_interval: int = 48

    # Package / player
    title: str = "ASCII Film"
    description: str = ""
    foreground: str = "#eeeeee"
    background: str = "#101010"
    loop: bool = True
    autoplay: str = "off"  # "off" | "muted"
    audio: bool = True
    audio_bitrate: str = "160k"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


FIELD_TYPES = {f.name: f.type for f in fields(EncodeConfig)}

# (min, max) inclusive ranges for numeric options.
RANGES: dict[str, tuple[float, float]] = {
    "fps": (1, 60),
    "columns": (40, 320),
    "min_rows": (1, 1000),
    "max_rows": (1, 1000),
    "oversample_x": (1, 16),
    "oversample_y": (1, 16),
    "max_frames": (1, 1_000_000),
    "font_size": (4, 200),
    "line_height": (0.5, 3.0),
    "brightness": (-1.0, 1.0),
    "contrast": (0.1, 5.0),
    "gamma": (0.1, 5.0),
    "levels_low_percentile": (0.0, 50.0),
    "levels_high_percentile": (50.0, 100.0),
    "detail": (0.0, 4.0),
    "dither": (0.0, 2.0),
    "variation": (0.0, 2.0),
    "seed": (0, 2**32 - 1),
    "stability": (0.0, 1.0),
    "cut_threshold": (0.01, 1.0),
    "keyframe_interval": (1, 10000),
}

INT_FIELDS = {"fps", "columns", "min_rows", "max_rows", "oversample_x", "oversample_y",
              "max_frames", "seed", "keyframe_interval"}
BOOL_FIELDS = {"allow_proportional_font", "auto_levels", "invert", "stabilization", "loop", "audio"}
STR_FIELDS = {"font", "glyphs", "title", "description", "foreground", "background",
              "autoplay", "audio_bitrate"}


def _coerce(name: str, value: Any) -> Any:
    if name == "scene_cuts":
        if not isinstance(value, list) or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 for v in value):
            raise ConfigError("scene_cuts: expected a list of non-negative seconds")
        return sorted(float(v) for v in value)
    if value is None:
        if name == "line_height":
            return None
        raise ConfigError(f"{name}: value must not be null")
    if name in BOOL_FIELDS:
        if not isinstance(value, bool):
            raise ConfigError(f"{name}: expected true/false, got {value!r}")
        return value
    if name in STR_FIELDS:
        if not isinstance(value, str):
            raise ConfigError(f"{name}: expected a string, got {value!r}")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{name}: expected a number, got {value!r}")
    if name in INT_FIELDS:
        if float(value) != int(value):
            raise ConfigError(f"{name}: expected an integer, got {value!r}")
        return int(value)
    return float(value)


def load_config_file(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {p}") from None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"config file {p} is not valid UTF-8 JSON: {exc}") from None
    if not isinstance(raw, dict):
        raise ConfigError(f"config file {p} must contain a JSON object")
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if key.startswith("$") or key.startswith("_"):
            continue  # comments such as "_comment" or "$schema"
        name = key.replace("-", "_")
        if name not in FIELD_TYPES:
            raise ConfigError(f"config file {p}: unknown option {key!r}")
        out[name] = value
    # Relative font paths in a config file are relative to the config file.
    if "font" in out and isinstance(out["font"], str) and not Path(out["font"]).is_absolute():
        candidate = (p.parent / out["font"]).resolve()
        if candidate.exists():
            out["font"] = str(candidate)
    return out


def build_config(config_path: str | Path | None = None,
                 overrides: dict[str, Any] | None = None) -> tuple[EncodeConfig, list[str]]:
    """Merge defaults, an optional JSON file and CLI overrides; validate the result.

    Returns the config and a list of human-readable warnings.
    """
    values: dict[str, Any] = {}
    if config_path is not None:
        values.update(load_config_file(config_path))
    for key, value in (overrides or {}).items():
        if value is not None:
            values[key] = value
    cfg = EncodeConfig()
    for name, value in values.items():
        if name not in FIELD_TYPES:
            raise ConfigError(f"unknown option {name!r}")
        setattr(cfg, name, _coerce(name, value))
    return cfg, validate(cfg)


def validate(cfg: EncodeConfig) -> list[str]:
    warnings: list[str] = []
    for name, (lo, hi) in RANGES.items():
        value = getattr(cfg, name)
        if value is None:
            continue
        if not (lo <= value <= hi):
            raise ConfigError(f"{name} must be between {lo:g} and {hi:g} (got {value:g})")
    if cfg.min_rows > cfg.max_rows:
        raise ConfigError("min_rows must not exceed max_rows")
    if cfg.levels_low_percentile >= cfg.levels_high_percentile:
        raise ConfigError("levels_low_percentile must be below levels_high_percentile")
    for name in ("foreground", "background"):
        if not HEX_COLOR.match(getattr(cfg, name)):
            raise ConfigError(f"{name} must be a #rrggbb color (got {getattr(cfg, name)!r})")
    if cfg.foreground.lower() == cfg.background.lower():
        raise ConfigError("foreground and background colors must differ")
    if cfg.autoplay not in ("off", "muted"):
        raise ConfigError("autoplay must be 'off' or 'muted'")
    if not re.fullmatch(r"\d{2,3}k", cfg.audio_bitrate):
        raise ConfigError("audio_bitrate must look like '128k'")
    if not cfg.glyphs:
        raise ConfigError("glyphs must not be empty")
    if len(cfg.title) > 200:
        raise ConfigError("title must be at most 200 characters")
    if len(cfg.description) > 2000:
        raise ConfigError("description must be at most 2000 characters")
    if cfg.columns > 240:
        warnings.append(f"{cfg.columns} columns produce large files and heavy browser rendering")
    if cfg.detail > 0 and cfg.oversample_x * cfg.oversample_y < 4:
        warnings.append("detail weighting needs oversample_x * oversample_y >= 4 to see shape")
    return warnings
