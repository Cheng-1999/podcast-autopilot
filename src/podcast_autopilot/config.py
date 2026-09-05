from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TOOLS_BIN = PROJECT_ROOT / "tools" / "ffmpeg" / "bin"
DEFAULT_MODELS_DIR = PROJECT_ROOT / "tools" / "models"

# Isolated filler tokens; multi-character entries only match if faster-whisper's
# word-level alignment happens to emit them as a single word (CJK word
# boundaries are not guaranteed, see README).
DEFAULT_FILLER_WORDS: tuple[str, ...] = ("嗯", "呃", "啊", "那個", "就是說", "然後")


class FFmpegNotFoundError(RuntimeError):
    pass


@dataclass
class AppConfig:
    ffmpeg_path: str | None = None
    loudness_target_i: float = -16.0
    loudness_target_tp: float = -1.5
    profile_name: str = "default"
    pauses: "PauseConfig" = None  # type: ignore[assignment]
    whisper_model_size: str = "small"
    filler_words: list[str] = field(default_factory=lambda: list(DEFAULT_FILLER_WORDS))
    filler_pause_threshold_s: float = 0.2
    filler_min_probability: float = 0.5
    denoise_engine: str = "auto"
    voice_chain: "VoiceChainConfig" = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.pauses is None:
            self.pauses = PauseConfig()
        if self.voice_chain is None:
            self.voice_chain = VoiceChainConfig(denoise_engine=self.denoise_engine)


@dataclass
class PauseConfig:
    noise: str = "-35dB"
    min_duration: float = 0.6
    max_keep: float = 1.5
    target: float = 0.6
    guard: float = 0.15
    min_segment: float = 0.5
    head: float = 0.3
    tail: float = 1.0
    max_removed_fraction: float = 0.25


@dataclass
class VoiceChainConfig:
    denoise_engine: str = "auto"
    highpass_hz: float = 80.0
    deesser_enabled: bool = True
    deesser_frequency: float = 0.5
    deesser_intensity: float = 0.3
    deesser_max: float = 0.5
    compressor_threshold_db: float = -18.0
    compressor_ratio: float = 3.0
    compressor_attack_ms: float = 15.0
    compressor_release_ms: float = 250.0
    loudness_target_i: float = -16.0
    loudness_target_tp: float = -1.5
    loudness_target_lra: float = 11.0
    adeclick: bool = False
    adeclip: bool = False


def load_config(config_path: Path | None = None) -> AppConfig:
    if config_path is None or not config_path.is_file():
        return AppConfig()
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    pauses = data.get("pauses") or {}
    voice = data.get("voice_chain") or {}
    denoise = data.get("denoise") or {}
    engine = str(denoise.get("engine", voice.get("denoise_engine", "auto")))
    return AppConfig(
        ffmpeg_path=data.get("ffmpeg_path"),
        loudness_target_i=float(data.get("loudness_target_i", -16.0)),
        loudness_target_tp=float(data.get("loudness_target_tp", -1.5)),
        profile_name=str(data.get("name", "default")),
        whisper_model_size=str(data.get("whisper_model_size", "small")),
        filler_words=list(data.get("filler_words", DEFAULT_FILLER_WORDS)),
        filler_pause_threshold_s=float(data.get("filler_pause_threshold_s", 0.2)),
        filler_min_probability=float(data.get("filler_min_probability", 0.5)),
        denoise_engine=engine,
        voice_chain=VoiceChainConfig(
            denoise_engine=engine,
            highpass_hz=float(voice.get("highpass_hz", 80.0)),
            deesser_enabled=bool(voice.get("deesser_enabled", True)),
            deesser_frequency=float(voice.get("deesser_frequency", 0.5)),
            deesser_intensity=float(voice.get("deesser_intensity", 0.3)),
            deesser_max=float(voice.get("deesser_max", 0.5)),
            compressor_threshold_db=float(voice.get("compressor_threshold_db", -18.0)),
            compressor_ratio=float(voice.get("compressor_ratio", 3.0)),
            compressor_attack_ms=float(voice.get("compressor_attack_ms", 15.0)),
            compressor_release_ms=float(voice.get("compressor_release_ms", 250.0)),
            loudness_target_i=float(voice.get("loudness_target_i", data.get("loudness_target_i", -16.0))),
            loudness_target_tp=float(voice.get("loudness_target_tp", data.get("loudness_target_tp", -1.5))),
            loudness_target_lra=float(voice.get("loudness_target_lra", 11.0)),
            adeclick=bool(voice.get("adeclick", False)),
            adeclip=bool(voice.get("adeclip", False)),
        ),
        pauses=PauseConfig(
            noise=str(pauses.get("noise", "-35dB")),
            min_duration=float(pauses.get("min_duration", pauses.get("d", 0.6))),
            max_keep=float(pauses.get("max_keep", 1.5)),
            target=float(pauses.get("target", 0.6)),
            guard=float(pauses.get("guard", 0.15)),
            min_segment=float(pauses.get("min_segment", 0.5)),
            head=float(pauses.get("head", 0.3)),
            tail=float(pauses.get("tail", 1.0)),
            max_removed_fraction=float(pauses.get("max_removed_fraction", 0.25)),
        ),
    )


def resolve_binary(name: str, configured_path: str | None = None) -> Path:
    """Resolve an ffmpeg-suite binary.

    Order: configured_path > PATH > tools/ffmpeg/bin. Fails closed with a
    message pointing at the README install steps.

    `configured_path` may be a directory (looked up for `<name>.exe`) or a
    path to one executable. If it names an executable with a different stem
    (e.g. ffmpeg.exe while resolving ffprobe), the sibling `<name>.exe` in
    the same directory is used, so a single `ffmpeg_path` setting serves
    both tools instead of returning ffmpeg.exe for ffprobe.
    """
    exe_name = f"{name}.exe" if os.name == "nt" else name

    if configured_path:
        configured = Path(configured_path)
        if configured.is_dir():
            candidate = configured / exe_name
        elif configured.stem.lower() == name.lower():
            candidate = configured
        else:
            candidate = configured.parent / exe_name
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
