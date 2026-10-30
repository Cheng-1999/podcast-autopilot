from __future__ import annotations

import json
import math
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

from .config import AppConfig, VoiceChainConfig, resolve_ffmpeg_binaries
from .audit import sha256_of_file
from .ffmpeg import FFmpegError, _parse_loudnorm_json, ffmpeg_version, measure_loudness, run_ffmpeg, run_ffprobe_json


class VoiceChainError(RuntimeError):
    pass


class Denoiser(ABC):
    name = "unknown"
    version = "unknown"

    @abstractmethod
    def process(self, path_in: Path, path_out: Path) -> None:
        raise NotImplementedError


class NoisereduceDenoiser(Denoiser):
    name = "noisereduce"

    def __init__(self) -> None:
        import noisereduce  # type: ignore
        self._nr = noisereduce
        self.version = str(getattr(noisereduce, "__version__", "unknown"))

    def process(self, path_in: Path, path_out: Path) -> None:
        import numpy as np
        from scipy.io import wavfile  # type: ignore

        sr, audio = wavfile.read(path_in)
        samples = np.asarray(audio, dtype=np.float32)
        if samples.ndim > 1:
            samples = samples.mean(axis=1)
        noise = samples[: max(1, min(len(samples), int(sr * 2.0)))]
        reduced = self._nr.reduce_noise(
            y=samples, sr=sr, y_noise=noise, stationary=True,
            prop_decrease=0.80, n_fft=2048, win_length=2048,
            hop_length=512, n_jobs=1,
        )
        wavfile.write(path_out, sr, np.asarray(reduced, dtype=np.float32))


class AfftdnDenoiser(Denoiser):
    name = "afftdn"
    version = "ffmpeg built-in"

    def __init__(self, config: AppConfig):
        self.config = config

    def process(self, path_in: Path, path_out: Path) -> None:
        run_ffmpeg(["-i", str(path_in), "-af", "afftdn=nr=12:nf=-25", "-c:a", "pcm_f32le", str(path_out)], self.config)


def build_filtergraph(profile: VoiceChainConfig, loudnorm: str | None = None) -> str:
    filters = [f"highpass=f={profile.highpass_hz:g}"]
    if profile.adeclick:
        filters.append("adeclick")
    if profile.adeclip:
        filters.append("adeclip")
    if profile.deesser_enabled:
        filters.append(f"deesser=f={profile.deesser_frequency:g}:i={profile.deesser_intensity:g}:m={profile.deesser_max:g}")
    # FFmpeg's acompressor makeup option is a linear gain, not an "auto" token.
    threshold = 10 ** (profile.compressor_threshold_db / 20.0)
    filters.append(
        f"acompressor=threshold={threshold:.6f}:ratio={profile.compressor_ratio:g}:"
        f"attack={profile.compressor_attack_ms:g}:release={profile.compressor_release_ms:g}:makeup=1.0"
    )
    if loudnorm:
        filters.append(loudnorm)
    return ",".join(filters)


# The look-ahead limiter clamps sample peaks; true peak (4x oversampled) can
# sit a little above that, so aim the ceiling this far under the TP target.
LIMITER_MARGIN_DB = 1.0
LOUDNESS_TOLERANCE_DB = 1.0
TRUE_PEAK_TOLERANCE_DB = 0.5
MAX_GAIN_DB = 40.0


def _gain_to_target_db(target_i: float, measured_i) -> float:
    """Linear gain (dB) that moves an integrated loudness onto the target; 0 for silence/unmeasurable input."""
    try:
        value = float(measured_i)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(value):
        return 0.0
    return max(-MAX_GAIN_DB, min(MAX_GAIN_DB, target_i - value))


def _within_targets(loudness: float, true_peak: float, profile: VoiceChainConfig) -> bool:
    return (
        abs(loudness - profile.loudness_target_i) <= LOUDNESS_TOLERANCE_DB
        and true_peak <= profile.loudness_target_tp + TRUE_PEAK_TOLERANCE_DB
    )


def _engine(config: AppConfig, requested: str) -> Denoiser | None:
    if requested == "off":
        return None
    if requested == "afftdn":
        return AfftdnDenoiser(config)
    if requested in {"auto", "noisereduce"}:
        try:
            return NoisereduceDenoiser()
        except Exception as exc:
            if requested == "noisereduce":
                raise VoiceChainError(f"noisereduce is unavailable: {exc}") from exc
            print(f"WARNING: noisereduce unavailable ({exc}); falling back to afftdn")
            return AfftdnDenoiser(config)
    raise VoiceChainError(f"Unknown denoise engine: {requested}")


def _source_sr(path: Path, config: AppConfig) -> int:
    streams = run_ffprobe_json(path, config).get("streams", [])
    if not streams or not streams[0].get("sample_rate"):
        raise VoiceChainError(f"Could not determine source sample rate for {path}")
    return int(streams[0]["sample_rate"])


def clean_audio(source: Path, out_dir: Path = Path("out"), config: AppConfig | None = None) -> tuple[Path, Path]:
    config = config or AppConfig()
    source, out_dir = Path(source), Path(out_dir)
    target = out_dir / source.stem
    target.mkdir(parents=True, exist_ok=True)
    output = target / f"{source.stem}.clean.wav"
    receipt_path = target / "receipt.json"
    sr = _source_sr(source, config)
    requested = config.voice_chain.denoise_engine

    with tempfile.TemporaryDirectory(prefix="podcast-autopilot-") as temp:
        tempdir = Path(temp)
        denoised = tempdir / "denoised.wav"
        engine = _engine(config, requested)
        input_path = source
        if engine:
            if engine.name == "noisereduce":
                internal = tempdir / "internal-48k.wav"
                run_ffmpeg(["-i", str(source), "-ar", "48000", "-ac", "1", "-c:a", "pcm_f32le", str(internal)], config)
                engine.process(internal, denoised)
            else:
                engine.process(source, denoised)
            input_path = denoised

        profile = config.voice_chain
        ffmpeg, _ = resolve_ffmpeg_binaries(config)
        target_i, target_tp = profile.loudness_target_i, profile.loudness_target_tp
        measure_filter = (
            f"loudnorm=I={target_i:g}:TP={target_tp:g}:LRA={profile.loudness_target_lra:g}:print_format=json"
        )

        def measure_through(graph: str) -> dict:
            proc = subprocess.run(
                [str(ffmpeg), "-hide_banner", "-nostats", "-i", str(input_path), "-af", graph, "-f", "null", "-"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            if proc.returncode:
                raise FFmpegError(f"voice chain measurement pass failed: {proc.stderr}")
            return _parse_loudnorm_json(proc.stderr)

        # Pass 0: bring the (denoised) input to nominal level *before* the
        # chain, so the compressor's absolute threshold behaves the same for
        # a -35 LUFS home recording as for a -20 LUFS studio one.
        input_measured = measure_through(measure_filter)
        pregain_db = _gain_to_target_db(target_i, input_measured.get("input_i"))
        chain = build_filtergraph(profile)
        ceiling_dbtp = target_tp - LIMITER_MARGIN_DB
        limiter = f"alimiter=limit={10 ** (ceiling_dbtp / 20.0):.4f}:attack=5:release=50:level=false"
        # The same limiter also guards the chain's input: ffmpeg's deesser
        # goes unstable (hundreds of dB of output) once samples exceed
        # 0 dBFS, which a single mic bump at 0 dBFS does after +18 dB of
        # pre-gain. Clamping first costs nothing on well-behaved material.
        pregain = f"volume={pregain_db:.2f}dB,{limiter}"

        # Pass 1: measure what the chain does to that nominal-level signal.
        measured = measure_through(f"{pregain},{chain},{measure_filter}")
        gain_db = _gain_to_target_db(target_i, measured.get("input_i"))

        # Pass 2: linear gain to the integrated target, then a look-ahead
        # limiter for the true-peak ceiling. ffmpeg's loudnorm cannot do this
        # itself: with linear=true it silently reverts to dynamic mode as soon
        # as the required gain would push a single transient (a mic bump at
        # 0 dBFS in a -35 LUFS take) over TP, and dynamic mode both undershoots
        # the integrated target by several dB and overshoots TP on real speech.
        # The output limiter runs 4x oversampled so it clamps *true* (inter-
        # sample) peaks: limiting at the native rate leaves ~1.7 dBTP of
        # overshoot on real speech, oversampled it is within ~0.1 dB.
        output_limiter = f"aresample={sr * 4},{limiter},aresample={sr}"
        final_graph = f"{pregain},{chain},volume={gain_db:.2f}dB,{output_limiter}"
        run_ffmpeg(["-i", str(input_path), "-af", final_graph, "-ar", str(sr), "-ac", "1", "-c:a", "pcm_f32le", str(output)], config)
        result = measure_loudness(output, config)
        loudness = float(result.get("input_i", "nan"))
        true_peak = float(result.get("input_tp", "nan"))

        if math.isfinite(loudness) and not _within_targets(loudness, true_peak, profile):
            # The limiter took some programme loudness with the peaks; nudge
            # the linear gain by the measured shortfall and render once more.
            gain_db += target_i - loudness
            final_graph = f"{pregain},{chain},volume={gain_db:.2f}dB,{output_limiter}"
            run_ffmpeg(["-i", str(input_path), "-af", final_graph, "-ar", str(sr), "-ac", "1", "-c:a", "pcm_f32le", str(output)], config)
            result = measure_loudness(output, config)
            loudness = float(result.get("input_i", "nan"))
            true_peak = float(result.get("input_tp", "nan"))

        if not math.isfinite(loudness) or not math.isfinite(true_peak) or not _within_targets(loudness, true_peak, profile):
            output.unlink(missing_ok=True)
            raise VoiceChainError(f"voice chain verification failed: LUFS={loudness}, TP={true_peak}")
    receipt = {
        "schema": "podcast-autopilot.voice-chain-receipt/v1",
        "source": {"path": str(source), "sha256": sha256_of_file(source)},
        "output": {"path": str(output), "sha256": sha256_of_file(output)},
        "engine": {"name": engine.name if engine else "off", "version": engine.version if engine else "off"},
        "ffmpeg_version": ffmpeg_version(config),
        "denoise_filtergraph": "afftdn=nr=12:nf=-25" if engine and engine.name == "afftdn" else None,
        "filtergraph": final_graph,
        "input_loudness": input_measured,
        "loudnorm_pass1": measured,
        "gain": {"pregain_db": round(pregain_db, 2), "gain_db": round(gain_db, 2), "limiter_ceiling_dbtp": ceiling_dbtp},
        "verification": {
            "lufs": loudness, "true_peak_dbtp": true_peak,
            "target_i": profile.loudness_target_i, "target_tp": profile.loudness_target_tp,
        },
    }
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return output, receipt_path
