from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .config import AppConfig, resolve_ffmpeg_binaries


class FFmpegError(RuntimeError):
    pass


def run_ffprobe_json(path: Path, config: AppConfig | None = None) -> dict:
    _, ffprobe = resolve_ffmpeg_binaries(config)
    cmd = [
        str(ffprobe),
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise FFmpegError(f"ffprobe failed for {path}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def run_ffmpeg(args: list[str], config: AppConfig | None = None) -> subprocess.CompletedProcess:
    ffmpeg, _ = resolve_ffmpeg_binaries(config)
    cmd = [str(ffmpeg), "-hide_banner", "-y", *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise FFmpegError(f"ffmpeg failed: {' '.join(cmd)}\n{result.stderr}")
    return result


def _parse_loudnorm_json(stderr_text: str) -> dict:
    start = stderr_text.rfind("{")
    end = stderr_text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise FFmpegError("Could not find loudnorm JSON block in ffmpeg output")
    return json.loads(stderr_text[start:end + 1])


def measure_loudness(path: Path, config: AppConfig | None = None) -> dict:
    """Run loudnorm in measure-only mode and parse the JSON block ffmpeg prints to stderr."""
    ffmpeg, _ = resolve_ffmpeg_binaries(config)
    cmd = [
        str(ffmpeg),
        "-hide_banner", "-nostats",
        "-i", str(path),
        "-af", "loudnorm=print_format=json",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise FFmpegError(f"loudnorm measure failed for {path}: {result.stderr.strip()}")
    return _parse_loudnorm_json(result.stderr)


def measure_mean_volume(path: Path, start: float, duration: float, config: AppConfig | None = None) -> float:
    """Mean volume in dBFS of a cropped window, via the volumedetect filter."""
    ffmpeg, _ = resolve_ffmpeg_binaries(config)
    cmd = [
        str(ffmpeg), "-hide_banner", "-nostats",
        "-ss", f"{start:.6f}", "-t", f"{duration:.6f}",
        "-i", str(path),
        "-af", "volumedetect",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise FFmpegError(f"volumedetect failed for {path}: {result.stderr.strip()}")
    match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", result.stderr)
    if not match:
        raise FFmpegError(f"volumedetect produced no mean_volume for {path}")
    return float(match.group(1))


def decode_pcm_s16le_mono(path: Path, config: AppConfig | None = None) -> bytes:
    """Decode `path` to raw little-endian 16-bit mono PCM, native sample rate."""
    ffmpeg, _ = resolve_ffmpeg_binaries(config)
    cmd = [
        str(ffmpeg), "-hide_banner", "-nostats",
        "-i", str(path), "-ac", "1",
        "-f", "s16le", "-acodec", "pcm_s16le", "-",
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise FFmpegError(f"pcm decode failed for {path}: {result.stderr.decode(errors='replace')}")
    return result.stdout


def ffmpeg_version(config: AppConfig | None = None) -> str:
    ffmpeg, _ = resolve_ffmpeg_binaries(config)
    result = subprocess.run([str(ffmpeg), "-version"], capture_output=True, text=True)
    return result.stdout.splitlines()[0] if result.stdout else "unknown"


def generate_synthetic_audio(path: Path, duration: float = 30.0, config: AppConfig | None = None) -> None:
    """Create a mono 44.1kHz WAV: a steady tone mixed with white noise, for selftest."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    args = [
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-f", "lavfi", "-i", f"anoisesrc=duration={duration}:color=white:amplitude=0.05",
        "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first,volume=0.8[out]",
        "-map", "[out]",
        "-ar", "44100", "-ac", "1",
        str(path),
    ]
    run_ffmpeg(args, config)
