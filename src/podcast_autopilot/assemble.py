"""Episode assembly: join parts, intro/outro, ducked BGM, chapters, MP3 export."""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from .audit import sha256_of_file
from .config import AppConfig, PauseConfig
from .ffmpeg import (
    FFmpegError,
    _parse_loudnorm_json,
    ffmpeg_version,
    measure_loudness,
    measure_mean_volume,
    resolve_ffmpeg_binaries,
    run_ffmpeg,
)
from .pauses import detect_silences
from .probe import probe_audio, probe_audio_format

SCHEMA_ID = "podcast-autopilot.assemble-receipt/v1"

ROOM_TONE_SAMPLE_S = 0.3
ROOM_TONE_GAP_S = 0.5
PINK_NOISE_AMPLITUDE = 0.0022
CROSSFADE_S = 1.0
BGM_FADE_IN_S = 2.0
BGM_FADE_OUT_S = 3.0
LOUDNESS_TOLERANCE_LU = 1.0
MAX_LOUDNORM_ATTEMPTS = 3
TP_TOLERANCE_DB = 0.3
MP3_TP_INITIAL_MARGIN_DB = 1.0
MAX_TP_ATTEMPTS = 3


class AssembleError(RuntimeError):
    pass


class DuckConfig(BaseModel):
    threshold: float = 0.03
    ratio: float = 8.0
    attack: float = 5.0
    release: float = 300.0


class BgmConfig(BaseModel):
    path: str
    gain_db: float = -18.0
    duck: DuckConfig = Field(default_factory=DuckConfig)


class ChapterEntry(BaseModel):
    start: str
    title: str


class TagsConfig(BaseModel):
    artist: str | None = None
    album: str | None = None
    year: int | None = None
    genre: str = "Podcast"
    comment: str | None = None


class EpisodeManifest(BaseModel):
    title: str
    episode: int
    parts: list[str]
    intro: str | None = None
    outro: str | None = None
    bgm: BgmConfig | None = None
    chapters: list[ChapterEntry] = Field(default_factory=list)
    tags: TagsConfig = Field(default_factory=TagsConfig)


def load_manifest(path: Path) -> EpisodeManifest:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return EpisodeManifest.model_validate(data)


_TIMECODE = re.compile(r"^(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)$")


def parse_timecode(value: str) -> float:
    """Parse "mm:ss", "hh:mm:ss" (fractional seconds allowed) or a bare number of seconds."""
    text = str(value).strip()
    if re.match(r"^\d+(?:\.\d+)?$", text):
        return float(text)
    match = _TIMECODE.match(text)
    if not match:
        raise AssembleError(f"invalid timecode: {value!r}")
    hours = float(match.group(1) or 0)
    minutes = float(match.group(2))
    seconds = float(match.group(3))
    return hours * 3600 + minutes * 60 + seconds


def _resolve(path_str: str, base_dir: Path) -> Path:
    path = Path(path_str)
    return path if path.is_absolute() else (base_dir / path)


def _layout(channels: int) -> str:
    return "mono" if channels == 1 else "stereo"


@dataclass
class _Format:
    sr: int
    channels: int


def _quietest_silence_start(part1: Path, config: AppConfig) -> float | None:
    """Start of the quietest detected silence in part1 at least ROOM_TONE_SAMPLE_S long."""
    probe_cfg = AppConfig(
        ffmpeg_path=config.ffmpeg_path,
        pauses=PauseConfig(noise="-30dB", min_duration=ROOM_TONE_SAMPLE_S),
    )
    silences = detect_silences(part1, probe_cfg)
    best: tuple[float, float] | None = None  # (mean_volume_db, sample_start)
    for start, end in silences:
        length = end - start
        if length < ROOM_TONE_SAMPLE_S:
            continue
        sample_start = start + (length - ROOM_TONE_SAMPLE_S) / 2
        volume = measure_mean_volume(part1, sample_start, ROOM_TONE_SAMPLE_S, config)
        if best is None or volume < best[0]:
            best = (volume, sample_start)
    return best[1] if best else None


def _build_room_tone_gap(part1: Path, fmt: _Format, tempdir: Path, config: AppConfig) -> Path:
    gap_path = tempdir / "room_tone_gap.wav"
    sample_start = _quietest_silence_start(part1, config)
    if sample_start is not None:
        sample_path = tempdir / "room_tone_sample.wav"
        run_ffmpeg([
            "-ss", f"{sample_start:.6f}", "-t", f"{ROOM_TONE_SAMPLE_S:.3f}",
            "-i", str(part1),
            "-ar", str(fmt.sr), "-ac", str(fmt.channels), "-c:a", "pcm_f32le",
            str(sample_path),
        ], config)
        run_ffmpeg([
            "-stream_loop", "-1", "-i", str(sample_path), "-t", f"{ROOM_TONE_GAP_S:.3f}",
            "-ar", str(fmt.sr), "-ac", str(fmt.channels), "-c:a", "pcm_f32le",
            str(gap_path),
        ], config)
    else:
        run_ffmpeg([
            "-f", "lavfi", "-i",
            f"anoisesrc=color=pink:amplitude={PINK_NOISE_AMPLITUDE:g}:duration={ROOM_TONE_GAP_S:g}:sample_rate={fmt.sr}",
            "-ac", str(fmt.channels), "-c:a", "pcm_f32le",
            str(gap_path),
        ], config)
    return gap_path


def _concat_parts_with_gaps(parts: list[Path], gap_path: Path, fmt: _Format, tempdir: Path, config: AppConfig) -> Path:
    output = tempdir / "body.wav"
    layout = _layout(fmt.channels)
    inputs: list[str] = []
    chunks: list[str] = []
    labels: list[str] = []
    idx = 0
    for i, part in enumerate(parts):
        inputs += ["-i", str(part)]
        label = f"p{idx}"
        chunks.append(f"[{idx}:a]aformat=sample_rates={fmt.sr}:channel_layouts={layout}[{label}]")
        labels.append(label)
        idx += 1
        if i < len(parts) - 1:
            inputs += ["-i", str(gap_path)]
            glabel = f"g{idx}"
            chunks.append(f"[{idx}:a]aformat=sample_rates={fmt.sr}:channel_layouts={layout}[{glabel}]")
            labels.append(glabel)
            idx += 1
    concat_refs = "".join(f"[{label}]" for label in labels)
    chunks.append(f"{concat_refs}concat=n={len(labels)}:v=0:a=1[body]")
    filter_complex = ";".join(chunks)
    run_ffmpeg([*inputs, "-filter_complex", filter_complex, "-map", "[body]", "-c:a", "pcm_f32le", str(output)], config)
    return output


def _crossfade_join(a: Path, b: Path, fmt: _Format, tempdir: Path, config: AppConfig, out_name: str) -> Path:
    """Join a then b with a CROSSFADE_S fade-out / fade-in at the seam.

    acrossfade runs with overlap disabled (o=0): the tail of `a` fades out
    over CROSSFADE_S and the head of `b` fades in over CROSSFADE_S, butt-joined.
    With the default overlapping crossfade every join would eat CROSSFADE_S of
    programme, which breaks the contract that the episode length equals
    intro + parts + gaps + outro.
    """
    output = tempdir / out_name
    layout = _layout(fmt.channels)
    filter_complex = (
        f"[0:a]aformat=sample_rates={fmt.sr}:channel_layouts={layout}[a0];"
        f"[1:a]aformat=sample_rates={fmt.sr}:channel_layouts={layout}[a1];"
        f"[a0][a1]acrossfade=d={CROSSFADE_S:g}:o=0[out]"
    )
    run_ffmpeg([
        "-i", str(a), "-i", str(b), "-filter_complex", filter_complex,
        "-map", "[out]", "-c:a", "pcm_f32le", str(output),
    ], config)
    return output


def _apply_bgm(voice: Path, bgm: BgmConfig, base_dir: Path, fmt: _Format, tempdir: Path, config: AppConfig) -> Path:
    bgm_path = _resolve(bgm.path, base_dir)
    voice_duration = probe_audio(voice, config)["duration"]
    layout = _layout(fmt.channels)
    looped = tempdir / "bgm_looped.wav"
    run_ffmpeg([
        "-stream_loop", "-1", "-i", str(bgm_path), "-t", f"{voice_duration:.6f}",
        "-ar", str(fmt.sr), "-ac", str(fmt.channels), "-c:a", "pcm_f32le",
        str(looped),
    ], config)
    fade_out_start = max(0.0, voice_duration - BGM_FADE_OUT_S)
    duck = bgm.duck
    output = tempdir / "mixed.wav"
    filter_complex = (
        f"[0:a]volume={bgm.gain_db:g}dB,afade=t=in:st=0:d={BGM_FADE_IN_S:g},"
        f"afade=t=out:st={fade_out_start:.6f}:d={BGM_FADE_OUT_S:g},"
        f"aformat=sample_rates={fmt.sr}:channel_layouts={layout}[bgm];"
        f"[1:a]aformat=sample_rates={fmt.sr}:channel_layouts={layout},asplit=2[voice_sc][voice_mix];"
        f"[bgm][voice_sc]sidechaincompress=threshold={duck.threshold:g}:ratio={duck.ratio:g}:"
        f"attack={duck.attack:g}:release={duck.release:g},apad[ducked];"
        # Voice is the first amix input so duration=first anchors the mix to the
        # programme length; sidechaincompress can end the BGM branch a few
        # hundred ms early, so it is padded with silence rather than allowed to
        # shorten the episode.
        f"[voice_mix][ducked]amix=inputs=2:duration=first:normalize=0[out]"
    )
    run_ffmpeg([
        "-i", str(looped), "-i", str(voice), "-filter_complex", filter_complex,
        "-map", "[out]", "-c:a", "pcm_f32le", str(output),
    ], config)
    return output


def _loudnorm_once(input_path: Path, output_path: Path, target_i: float, target_tp: float, target_lra: float, fmt: _Format, config: AppConfig) -> dict:
    ffmpeg, _ = resolve_ffmpeg_binaries(config)
    measure_filter = f"loudnorm=I={target_i:g}:TP={target_tp:g}:LRA={target_lra:g}:print_format=json"
    first = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-nostats", "-i", str(input_path), "-af", measure_filter, "-f", "null", "-"],
        capture_output=True, text=True,
    )
    if first.returncode:
        raise FFmpegError(f"assemble loudnorm measure pass failed: {first.stderr}")
    measured = _parse_loudnorm_json(first.stderr)
    loudnorm = (
        f"loudnorm=I={target_i:g}:TP={target_tp:g}:LRA={target_lra:g}:"
        f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:measured_LRA={measured['input_lra']}:"
        f"measured_thresh={measured['input_thresh']}:offset={measured.get('target_offset', 0)}:linear=true:print_format=summary"
    )
    layout = _layout(fmt.channels)
    run_ffmpeg([
        "-i", str(input_path), "-af", loudnorm,
        "-ar", str(fmt.sr), "-ac", str(fmt.channels), "-c:a", "pcm_f32le",
        str(output_path),
    ], config)
    return measured


def _loudnorm_to_lufs(input_path: Path, fmt: _Format, target_i: float, target_tp: float, target_lra: float, tempdir: Path, config: AppConfig) -> Path:
    """Two-pass loudnorm, iterated: a single linear pass can undershoot on very
    wide-dynamic-range sources (loudnorm silently falls back to its adaptive
    'dynamic' mode when a linear gain would blow the true-peak ceiling), so
    re-measuring and re-applying against the fresh output converges within a
    couple of attempts instead of leaving the episode off target. Peak
    ceiling is enforced later, against the exported MP3, since lossy encoding
    can add its own inter-sample overshoot on top of anything limited here.
    """
    current = input_path
    for attempt in range(MAX_LOUDNORM_ATTEMPTS):
        candidate = tempdir / f"loudnorm-{attempt}.wav"
        _loudnorm_once(current, candidate, target_i, target_tp, target_lra, fmt, config)
        current = candidate
        result = measure_loudness(current, config)
        lufs = float(result.get("input_i", "nan"))
        if abs(lufs - target_i) <= LOUDNESS_TOLERANCE_LU:
            break
    return current


def _apply_peak_ceiling(input_path: Path, fmt: _Format, ceiling_db: float, tempdir: Path, config: AppConfig, attempt: int) -> Path:
    output = tempdir / f"peak-ceiling-{attempt}.wav"
    limit = 10 ** (ceiling_db / 20.0)
    run_ffmpeg([
        "-i", str(input_path), "-af", f"alimiter=limit={limit:.6f}:level=0",
        "-ar", str(fmt.sr), "-ac", str(fmt.channels), "-c:a", "pcm_f32le",
        str(output),
    ], config)
    return output


def _format_ffmetadata_time(seconds: float) -> int:
    return int(round(seconds * 1000))


def _chapter_starts(chapters: list[ChapterEntry]) -> list[float]:
    """Parse and validate chapter starts: finite, non-negative, strictly increasing."""
    starts: list[float] = []
    for i, chapter in enumerate(chapters):
        start = parse_timecode(chapter.start)
        if not math.isfinite(start) or start < 0:
            raise AssembleError(f"chapter {i + 1} ({chapter.title!r}) has invalid start {chapter.start!r}")
        if starts and start <= starts[-1]:
            raise AssembleError(
                f"chapter {i + 1} ({chapter.title!r}) starts at {chapter.start!r}, "
                f"not after the previous chapter ({chapters[i - 1].start!r}); chapters must be in increasing order"
            )
        starts.append(start)
    return starts


def _check_chapters_within(chapters: list[ChapterEntry], starts: list[float], duration: float) -> None:
    for chapter, start in zip(chapters, starts):
        if start >= duration:
            raise AssembleError(
                f"chapter {chapter.title!r} starts at {chapter.start!r} ({start:.3f}s) "
                f"but the episode is only {duration:.3f}s long"
            )


def _write_chapter_files(chapters: list[ChapterEntry], duration: float, out_dir: Path) -> tuple[Path, Path, Path]:
    starts = _chapter_starts(chapters)
    _check_chapters_within(chapters, starts, duration)
    entries = []
    for i, chapter in enumerate(chapters):
        start = starts[i]
        end = starts[i + 1] if i + 1 < len(chapters) else duration
        entries.append({"start": start, "end": end, "title": chapter.title})

    ffmetadata_lines = [";FFMETADATA1"]
    for entry in entries:
        ffmetadata_lines.append("[CHAPTER]")
        ffmetadata_lines.append("TIMEBASE=1/1000")
        ffmetadata_lines.append(f"START={_format_ffmetadata_time(entry['start'])}")
        ffmetadata_lines.append(f"END={_format_ffmetadata_time(entry['end'])}")
        ffmetadata_lines.append(f"title={entry['title']}")
    ffmetadata_path = out_dir / "chapters.ffmetadata"
    ffmetadata_path.write_text("\n".join(ffmetadata_lines) + "\n", encoding="utf-8")

    chapters_json_path = out_dir / "chapters.json"
    chapters_json_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")

    nero_lines = []
    for i, entry in enumerate(entries, 1):
        h, rem = divmod(entry["start"], 3600)
        m, s = divmod(rem, 60)
        nero_lines.append(f"CHAPTER{i:02d}={int(h):02d}:{int(m):02d}:{s:06.3f}")
        nero_lines.append(f"CHAPTER{i:02d}NAME={entry['title']}")
    chapters_txt_path = out_dir / "chapters.txt"
    chapters_txt_path.write_text("\n".join(nero_lines) + ("\n" if nero_lines else ""), encoding="utf-8")

    return ffmetadata_path, chapters_json_path, chapters_txt_path


def _export_mp3(
    mixed_wav: Path,
    ffmetadata_path: Path | None,
    output_path: Path,
    is_mono: bool,
    title: str,
    tags: TagsConfig,
    episode_number: int,
    config: AppConfig,
) -> None:
    args: list[str] = ["-i", str(mixed_wav)]
    metadata_map: list[str] = []
    if ffmetadata_path is not None:
        args += ["-i", str(ffmetadata_path)]
        metadata_map = ["-map_metadata", "1"]
    args += ["-map", "0:a", *metadata_map]

    args += ["-id3v2_version", "3", "-write_id3v1", "1"]
    args += ["-metadata", f"title={title}"]
    if tags.artist:
        args += ["-metadata", f"artist={tags.artist}"]
    if tags.album:
        args += ["-metadata", f"album={tags.album}"]
    if tags.year is not None:
        args += ["-metadata", f"date={tags.year}"]
    args += ["-metadata", f"genre={tags.genre}"]
    if tags.comment:
        args += ["-metadata", f"comment={tags.comment}"]
    args += ["-metadata", f"track={episode_number}"]

    bitrate = "96k" if is_mono else "128k"
    args += ["-c:a", "libmp3lame", "-b:a", bitrate, "-ar", "44100", "-ac", "1" if is_mono else "2"]
    if not is_mono:
        args += ["-joint_stereo", "1"]

    # Render to a same-directory temp file and rename into place only once ffmpeg exits
    # successfully. get_deliverables (server/routes.py) exposes final_mp3 as soon as
    # output_path exists, but ffmpeg creates+truncates its destination the instant it
    # opens it -- well before encoding finishes, and this function reruns for every TP
    # retry attempt. A request landing mid-write (or mid-retry) would otherwise stream a
    # partial/stale MP3, one source of the intermittent "file won't load" reports.
    rendered = output_path.with_name(f".{output_path.stem}.tmp-{os.getpid()}{output_path.suffix}")
    args.append(str(rendered))
    try:
        run_ffmpeg(args, config)
        os.replace(rendered, output_path)
    finally:
        rendered.unlink(missing_ok=True)


def assemble_episode(manifest_path: Path, out_dir: Path = Path("out"), config: AppConfig | None = None) -> dict:
    manifest_path = Path(manifest_path)
    manifest = load_manifest(manifest_path)
    base_dir = manifest_path.resolve().parent
    return assemble_from_manifest(
        manifest, base_dir, out_dir, config,
        manifest_record={"path": str(manifest_path), "sha256": sha256_of_file(manifest_path)},
    )


def assemble_from_manifest(
    manifest: EpisodeManifest,
    base_dir: Path,
    out_dir: Path = Path("out"),
    config: AppConfig | None = None,
    manifest_record: dict | None = None,
) -> dict:
    """Assemble an already-loaded manifest whose `parts` point at final, edited part audio.

    Used directly by `run` (which builds this manifest from per-part apply
    outputs) as well as by `assemble_episode` (which loads it from a YAML
    file on disk).
    """
    config = config or AppConfig()
    base_dir = Path(base_dir)

    part_paths = [_resolve(p, base_dir) for p in manifest.parts]
    if not part_paths:
        raise AssembleError("manifest has no parts")
    for part in part_paths:
        if not part.is_file():
            raise AssembleError(f"part not found: {part}")

    intro_path = _resolve(manifest.intro, base_dir) if manifest.intro else None
    outro_path = _resolve(manifest.outro, base_dir) if manifest.outro else None
    bgm_path = _resolve(manifest.bgm.path, base_dir) if manifest.bgm else None
    for label, path in (("intro", intro_path), ("outro", outro_path), ("bgm", bgm_path)):
        if path is not None and not path.is_file():
            raise AssembleError(f"{label} not found: {path}")
    for label, path in (("intro", intro_path), ("outro", outro_path)):
        if path is not None and probe_audio_format(path, config)["duration"] < CROSSFADE_S:
            raise AssembleError(f"{label} {path} is shorter than the {CROSSFADE_S:g}s crossfade")

    # Fail fast on malformed chapters (order, negativity) before minutes of ffmpeg
    # work; the duration bound is checked once the final length is known.
    chapter_starts = _chapter_starts(manifest.chapters)

    part_infos = [probe_audio_format(part, config) for part in part_paths]
    is_mono = all(info["channels"] == 1 for info in part_infos)
    fmt = _Format(sr=int(part_infos[0]["sr"]), channels=1 if is_mono else 2)

    stem = f"ep{manifest.episode:02d}"
    target_dir = Path(out_dir) / stem
    target_dir.mkdir(parents=True, exist_ok=True)

    input_records = [{"path": str(part), "sha256": sha256_of_file(part)} for part in part_paths]

    with tempfile.TemporaryDirectory(prefix="podcast-autopilot-assemble-") as temp:
        tempdir = Path(temp)

        if len(part_paths) > 1:
            gap_path = _build_room_tone_gap(part_paths[0], fmt, tempdir, config)
            body = _concat_parts_with_gaps(part_paths, gap_path, fmt, tempdir, config)
        else:
            body = part_paths[0]

        voice = body
        if intro_path is not None:
            input_records.append({"path": str(intro_path), "sha256": sha256_of_file(intro_path)})
            voice = _crossfade_join(intro_path, voice, fmt, tempdir, config, "with_intro.wav")
        if outro_path is not None:
            input_records.append({"path": str(outro_path), "sha256": sha256_of_file(outro_path)})
            voice = _crossfade_join(voice, outro_path, fmt, tempdir, config, "with_outro.wav")

        mixed = voice
        if manifest.bgm and bgm_path is not None:
            input_records.append({"path": str(bgm_path), "sha256": sha256_of_file(bgm_path)})
            mixed = _apply_bgm(voice, manifest.bgm, base_dir, fmt, tempdir, config)

        loud_normalized = _loudnorm_to_lufs(
            mixed, fmt,
            config.loudness_target_i, config.loudness_target_tp, 11.0,
            tempdir, config,
        )

        duration = probe_audio_format(loud_normalized, config)["duration"]

        ffmetadata_path = None
        chapters_json_path = None
        chapters_txt_path = None
        if manifest.chapters:
            _check_chapters_within(manifest.chapters, chapter_starts, duration)
            ffmetadata_path, chapters_json_path, chapters_txt_path = _write_chapter_files(
                manifest.chapters, duration, target_dir
            )

        # MP3 encoding adds inter-sample "true peak" overshoot on top of any
        # sample-peak limiting done on the WAV, so the ceiling fed to the
        # limiter is measured and corrected against the actual exported MP3
        # rather than trusted from the WAV alone. Fail closed: an MP3 that is
        # still over the ceiling after MAX_TP_ATTEMPTS is an error, not a
        # silently accepted export.
        output_mp3 = target_dir / f"{stem}.mp3"
        tp_ceiling = config.loudness_target_tp + TP_TOLERANCE_DB
        ceiling_db = config.loudness_target_tp - MP3_TP_INITIAL_MARGIN_DB
        loudness: dict = {}
        tp = math.nan
        for attempt in range(MAX_TP_ATTEMPTS):
            final_wav = _apply_peak_ceiling(loud_normalized, fmt, ceiling_db, tempdir, config, attempt)
            _export_mp3(final_wav, ffmetadata_path, output_mp3, is_mono, manifest.title, manifest.tags, manifest.episode, config)
            loudness = measure_loudness(output_mp3, config)
            tp = float(loudness.get("input_tp", "nan"))
            if math.isfinite(tp) and tp <= tp_ceiling:
                break
            ceiling_db -= (tp - config.loudness_target_tp) + 0.5 if math.isfinite(tp) else 1.0
        else:
            output_mp3.unlink(missing_ok=True)
            raise AssembleError(
                f"true peak {tp:.2f} dBTP still above {config.loudness_target_tp:g} dBTP "
                f"(+{TP_TOLERANCE_DB:g} dB tolerance) after {MAX_TP_ATTEMPTS} limiter passes; "
                "no MP3 written"
            )

    output_info = probe_audio_format(output_mp3, config)

    receipt = {
        "schema": SCHEMA_ID,
        "created": datetime.now(timezone.utc).isoformat(),
        "manifest": manifest_record,
        "inputs": input_records,
        "output": {"path": str(output_mp3), "sha256": sha256_of_file(output_mp3)},
        "duration": output_info["duration"],
        "loudness": {
            "input_i": float(loudness.get("input_i", "nan")),
            "input_tp": float(loudness.get("input_tp", "nan")),
        },
        "ffmpeg_version": ffmpeg_version(config),
        "chapters": str(chapters_json_path) if chapters_json_path else None,
    }
    receipt_path = target_dir / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "output": output_mp3,
        "receipt": receipt_path,
        "chapters_json": chapters_json_path,
        "chapters_txt": chapters_txt_path,
        "duration": duration,
        "loudness": receipt["loudness"],
    }
