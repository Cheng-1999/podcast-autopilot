from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from podcast_autopilot.assemble import AssembleError, assemble_episode
from podcast_autopilot.config import AppConfig, resolve_ffmpeg_binaries
from podcast_autopilot.ffmpeg import run_ffmpeg

VOICE_HZ = 4000
BGM_HZ = 200


def _make_tone(path: Path, duration: float, config: AppConfig, freq: int = VOICE_HZ, amplitude: float = 0.8) -> None:
    run_ffmpeg([
        "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=44100:duration={duration}",
        "-af", f"volume={amplitude}",
        "-ac", "1", "-c:a", "pcm_f32le",
        str(path),
    ], config)


def _make_silence(path: Path, duration: float, config: AppConfig) -> None:
    run_ffmpeg([
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono", "-t", f"{duration}",
        "-ac", "1", "-c:a", "pcm_f32le",
        str(path),
    ], config)


def _concat(paths: list[Path], out_path: Path, config: AppConfig) -> None:
    inputs: list[str] = []
    for p in paths:
        inputs += ["-i", str(p)]
    labels = "".join(f"[{i}:a]" for i in range(len(paths)))
    filter_complex = f"{labels}concat=n={len(paths)}:v=0:a=1[out]"
    run_ffmpeg([*inputs, "-filter_complex", filter_complex, "-map", "[out]", "-c:a", "pcm_f32le", str(out_path)], config)


def _mean_level_db(path: Path, start: float, duration: float, bandpass_hz: int, config: AppConfig) -> float:
    """RMS level (dB) of a cropped window, bandpass-filtered around a frequency, via astats.

    A single biquad bandpass only rolls off gently, so the voice tone leaks
    through enough to swamp the (heavily ducked) BGM band during speech;
    cascading two stages doubles the rejection and isolates the BGM level.
    """
    ffmpeg, _ = resolve_ffmpeg_binaries(config)
    bp = f"bandpass=f={bandpass_hz}:width_type=h:w=100"
    cmd = [
        str(ffmpeg), "-hide_banner", "-nostats",
        "-ss", f"{start:.6f}", "-t", f"{duration:.6f}",
        "-i", str(path),
        "-af", f"{bp},{bp},astats=metadata=0",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    match = re.search(r"RMS level dB:\s*(-?\d+(?:\.\d+)?)", result.stderr)
    assert match, f"no RMS level found in astats output:\n{result.stderr}"
    return float(match.group(1))


@pytest.fixture
def config() -> AppConfig:
    return AppConfig()


def _build_episode(tmp_path: Path, config: AppConfig) -> tuple[Path, dict]:
    """part1 = 2s tone + 3s silence (speech gap) + 2s tone; part2 = 2s tone; bgm = continuous low tone."""
    part1_a = tmp_path / "p1a.wav"
    part1_gap = tmp_path / "p1gap.wav"
    part1_b = tmp_path / "p1b.wav"
    _make_tone(part1_a, 2.0, config)
    _make_silence(part1_gap, 3.0, config)
    _make_tone(part1_b, 2.0, config)
    part1 = tmp_path / "EP-1.wav"
    _concat([part1_a, part1_gap, part1_b], part1, config)

    part2 = tmp_path / "EP-2.wav"
    _make_tone(part2, 2.0, config)

    bgm = tmp_path / "bgm.wav"
    _make_tone(bgm, 10.0, config, freq=BGM_HZ, amplitude=0.5)

    manifest = {
        "title": "Test Episode",
        "episode": 1,
        "parts": ["EP-1.wav", "EP-2.wav"],
        "bgm": {
            "path": "bgm.wav",
            "gain_db": -18,
            "duck": {"threshold": 0.03, "ratio": 8, "attack": 5, "release": 300},
        },
        "chapters": [
            {"start": "00:00", "title": "Start"},
            {"start": "00:05", "title": "Middle"},
        ],
        "tags": {"artist": "Tester", "album": "Test Show", "year": 2026, "genre": "Podcast", "comment": "unit test"},
    }
    manifest_path = tmp_path / "episode.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
    return manifest_path, manifest


def test_assemble_duration_chapters_and_bgm_ducking(tmp_path: Path, config: AppConfig):
    manifest_path, manifest = _build_episode(tmp_path, config)
    out_dir = tmp_path / "out"

    result = assemble_episode(manifest_path, out_dir, config)

    output_mp3 = result["output"]
    assert output_mp3.is_file()

    # (a) duration = parts + gap between parts, within 100 ms.
    # part1 = 2+3+2 = 7s, part2 = 2s, one 0.5s room-tone gap between them.
    expected_duration = 7.0 + 0.5 + 2.0
    assert abs(result["duration"] - expected_duration) <= 0.1

    # (b) chapters appear in ffprobe -show_chapters.
    ffmpeg, ffprobe = resolve_ffmpeg_binaries(config)
    probe = subprocess.run(
        [str(ffprobe), "-v", "error", "-print_format", "json", "-show_chapters", str(output_mp3)],
        capture_output=True, text=True,
    )
    assert probe.returncode == 0, probe.stderr
    chapters = json.loads(probe.stdout)["chapters"]
    assert len(chapters) == 2
    titles = [c["tags"]["title"] for c in chapters]
    assert titles == ["Start", "Middle"]

    # (c) BGM level during speech is >= 10 dB below BGM level during the 3 s speech gap.
    # part1 timeline: tone [0-2), silence [2-5), tone [5-7). Speech window sits well
    # inside the first tone; gap window sits well inside the silence, clear of the
    # sidechaincompress attack/release ramps at either edge.
    speech_level = _mean_level_db(output_mp3, 0.5, 1.0, BGM_HZ, config)
    gap_level = _mean_level_db(output_mp3, 2.6, 1.8, BGM_HZ, config)
    assert gap_level - speech_level >= 10.0, f"gap={gap_level} speech={speech_level}"


def test_assemble_without_bgm_or_chapters(tmp_path: Path, config: AppConfig):
    part1 = tmp_path / "solo.wav"
    _make_tone(part1, 1.5, config)
    manifest = {
        "title": "Solo",
        "episode": 2,
        "parts": ["solo.wav"],
    }
    manifest_path = tmp_path / "episode.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest), encoding="utf-8")

    result = assemble_episode(manifest_path, tmp_path / "out", config)
    assert result["output"].is_file()
    assert abs(result["duration"] - 1.5) <= 0.1
    assert result["chapters_json"] is None


def _format_tags(path: Path, config: AppConfig) -> dict:
    _, ffprobe = resolve_ffmpeg_binaries(config)
    probe = subprocess.run(
        [str(ffprobe), "-v", "error", "-print_format", "json", "-show_format", str(path)],
        capture_output=True, text=True,
    )
    assert probe.returncode == 0, probe.stderr
    return json.loads(probe.stdout)["format"].get("tags", {})


def _write_manifest(tmp_path: Path, manifest: dict) -> Path:
    manifest_path = tmp_path / "episode.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
    return manifest_path


def test_assemble_intro_outro_keep_full_duration_title_tag_and_true_peak(tmp_path: Path, config: AppConfig):
    """Crossfades must not shorten the episode: duration = intro + parts + gaps + outro."""
    _make_tone(tmp_path / "intro.wav", 2.0, config, freq=600)
    _make_tone(tmp_path / "outro.wav", 1.5, config, freq=800)
    _make_tone(tmp_path / "EP-1.wav", 3.0, config)
    _make_tone(tmp_path / "EP-2.wav", 2.0, config)
    manifest_path = _write_manifest(tmp_path, {
        "title": "Intro Outro Episode",
        "episode": 4,
        "parts": ["EP-1.wav", "EP-2.wav"],
        "intro": "intro.wav",
        "outro": "outro.wav",
        "tags": {"artist": "Tester"},
    })

    result = assemble_episode(manifest_path, tmp_path / "out", config)

    expected_duration = 2.0 + 3.0 + 0.5 + 2.0 + 1.5
    assert abs(result["duration"] - expected_duration) <= 0.1, result["duration"]

    tags = {k.lower(): v for k, v in _format_tags(result["output"], config).items()}
    assert tags.get("title") == "Intro Outro Episode"
    assert tags.get("artist") == "Tester"
    assert tags.get("track") == "4"

    receipt = json.loads(result["receipt"].read_text(encoding="utf-8"))
    assert receipt["loudness"]["input_tp"] <= config.loudness_target_tp + 0.3, receipt["loudness"]
    assert len(receipt["inputs"]) == 4  # two parts + intro + outro


@pytest.mark.parametrize("key,value", [("intro", "missing-intro.wav"), ("outro", "missing-outro.wav")])
def test_assemble_rejects_missing_intro_or_outro(tmp_path: Path, config: AppConfig, key: str, value: str):
    _make_tone(tmp_path / "solo.wav", 1.5, config)
    manifest_path = _write_manifest(tmp_path, {"title": "Solo", "episode": 5, "parts": ["solo.wav"], key: value})
    with pytest.raises(AssembleError, match=f"{key} not found"):
        assemble_episode(manifest_path, tmp_path / "out", config)
    assert not (tmp_path / "out" / "ep05" / "ep05.mp3").exists()


def test_assemble_rejects_missing_bgm(tmp_path: Path, config: AppConfig):
    _make_tone(tmp_path / "solo.wav", 1.5, config)
    manifest_path = _write_manifest(tmp_path, {
        "title": "Solo", "episode": 6, "parts": ["solo.wav"], "bgm": {"path": "no-such-bgm.wav"},
    })
    with pytest.raises(AssembleError, match="bgm not found"):
        assemble_episode(manifest_path, tmp_path / "out", config)


@pytest.mark.parametrize("chapters,message", [
    ([{"start": "00:05", "title": "B"}, {"start": "00:03", "title": "A"}], "increasing order"),
    ([{"start": "00:02", "title": "A"}, {"start": "00:02", "title": "B"}], "increasing order"),
    ([{"start": "-5", "title": "A"}], "invalid timecode"),
    ([{"start": "00:10", "title": "Past the end"}], "only"),
])
def test_assemble_rejects_malformed_chapters(tmp_path: Path, config: AppConfig, chapters: list, message: str):
    _make_tone(tmp_path / "solo.wav", 1.5, config)
    manifest_path = _write_manifest(tmp_path, {
        "title": "Solo", "episode": 7, "parts": ["solo.wav"], "chapters": chapters,
    })
    with pytest.raises(AssembleError, match=message):
        assemble_episode(manifest_path, tmp_path / "out", config)
    assert not (tmp_path / "out" / "ep07" / "chapters.json").exists()
