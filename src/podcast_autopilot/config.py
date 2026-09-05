from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TOOLS_BIN = PROJECT_ROOT / "tools" / "ffmpeg" / "bin"


class FFmpegNotFoundError(RuntimeError):
    pass


@dataclass
class AppConfig:
    ffmpeg_path: str | None = None
    loudness_target_i: float = -16.0
    loudness_target_tp: float = -1.5
    profile_name: str = "default"


def load_config(config_path: Path | None = None) -> AppConfig:
    if config_path is None or not config_path.is_file():
        return AppConfig()
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return AppConfig(
        ffmpeg_path=data.get("ffmpeg_path"),
        loudness_target_i=float(data.get("loudness_target_i", -16.0)),
        loudness_target_tp=float(data.get("loudness_target_tp", -1.5)),
        profile_name=str(data.get("name", "default")),
    )


def resolve_binary(name: str, configured_path: str | None = None) -> Path:
    """Resolve an ffmpeg-suite binary.

    Order: configured_path (dir or exe) > PATH > tools/ffmpeg/bin. Fails
    closed with a message pointing at the README install steps.
    """
    exe_name = f"{name}.exe" if os.name == "nt" else name

    if configured_path:
        configured = Path(configured_path)
        candidate = configured / exe_name if configured.is_dir() else configured
        if candidate.is_file():
            return candidate

    found_on_path = shutil.which(name)
    if found_on_path:
        return Path(found_on_path)

    bundled = DEFAULT_TOOLS_BIN / exe_name
    if bundled.is_file():
        return bundled

    raise FFmpegNotFoundError(
        f"Could not find '{name}'. Install it with "
        f"`winget install Gyan.FFmpeg`, add it to PATH, or place it in "
        f"{DEFAULT_TOOLS_BIN} (see README.md)."
    )


def resolve_ffmpeg_binaries(config: AppConfig | None = None) -> tuple[Path, Path]:
    config = config or AppConfig()
    ffmpeg = resolve_binary("ffmpeg", config.ffmpeg_path)
    ffprobe = resolve_binary("ffprobe", config.ffmpeg_path)
    return ffmpeg, ffprobe
