from __future__ import annotations

from pathlib import Path

from .config import AppConfig
from .ffmpeg import measure_loudness, run_ffprobe_json


def probe_audio(path: Path, config: AppConfig | None = None) -> dict:
    """Return codec/format info (ffprobe) plus integrated loudness (ffmpeg loudnorm measure pass)."""
    path = Path(path)
    info = run_ffprobe_json(path, config)

    audio_streams = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    if not audio_streams:
        raise ValueError(f"No audio stream found in {path}")
    stream = audio_streams[0]
    fmt = info.get("format", {})

    duration_raw = fmt.get("duration") or stream.get("duration")
    duration = float(duration_raw) if duration_raw is not None else 0.0

    loudness = measure_loudness(path, config)

    return {
        "path": str(path),
        "codec": stream.get("codec_name"),
        "sr": int(stream["sample_rate"]) if stream.get("sample_rate") else None,
        "channels": stream.get("channels"),
        "sample_fmt": stream.get("sample_fmt"),
        "duration": duration,
        "input_i": float(loudness.get("input_i", "nan")),
        "input_tp": float(loudness.get("input_tp", "nan")),
        "input_lra": float(loudness.get("input_lra", "nan")),
        "input_thresh": float(loudness.get("input_thresh", "nan")),
    }
