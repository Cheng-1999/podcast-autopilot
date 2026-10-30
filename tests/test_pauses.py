from __future__ import annotations

from pathlib import Path

from podcast_autopilot.config import AppConfig, PauseConfig
from podcast_autopilot.ffmpeg import run_ffmpeg
from podcast_autopilot.pauses import ABSOLUTE_NOISE_FALLBACK, build_pause_plan, resolve_noise_threshold


def test_resolve_noise_threshold_relative_and_absolute():
    assert resolve_noise_threshold("-35dB", -16.0) == "-35dB"
    assert resolve_noise_threshold(" -40dB ", None) == "-40dB"
    assert resolve_noise_threshold("0LU", -16.5) == "-16.50dB"
    assert resolve_noise_threshold("-3LU", -34.6) == "-37.60dB"
    assert resolve_noise_threshold("+2.5 lu", -20.0) == "-17.50dB"
    assert resolve_noise_threshold("0LU", None) == ABSOLUTE_NOISE_FALLBACK
    assert resolve_noise_threshold("0LU", float("-inf")) == ABSOLUTE_NOISE_FALLBACK
    assert PauseConfig().noise == "0LU"


def _normalised_take_with_noisy_gap(path: Path) -> None:
    """A loud (-18 dBFS peak, ~-22 LUFS) tone with a 2.5 s gap at 4.0-6.5 s whose
    floor is pink noise at ~-28 dBFS: what a `clean`ed part looks like. The
    gap is a real pause, but it never drops under the old absolute -35dB."""
    run_ffmpeg([
        "-f", "lavfi", "-i", "sine=frequency=220:duration=10",
        "-f", "lavfi", "-i", "anoisesrc=duration=10:color=pink:amplitude=0.04:seed=7",
        "-filter_complex",
        "[0:a]volume='if(between(t,4,6.5),0,1)':eval=frame[tone];"
        "[tone][1:a]amix=inputs=2:duration=first:normalize=0[out]",
        "-map", "[out]", "-ar", "44100", "-ac", "1", "-c:a", "pcm_f32le", str(path),
    ])


def test_relative_threshold_finds_pause_in_normalised_audio_where_absolute_does_not(tmp_path: Path):
    source = tmp_path / "loud-with-gap.wav"
    _normalised_take_with_noisy_gap(source)

    relative = build_pause_plan(source, AppConfig(pauses=PauseConfig(noise="0LU")))
    cuts = [item for item in relative.items if item.kind == "cut"]
    assert len(cuts) == 1, [(i.kind, i.start, i.end, i.reason) for i in relative.items]
    assert 4.0 <= cuts[0].start <= 4.6
    assert 5.9 <= cuts[0].end <= 6.5
    assert cuts[0].end - cuts[0].start >= 1.5

    absolute = build_pause_plan(source, AppConfig(pauses=PauseConfig(noise="-35dB")))
    assert [item.kind for item in absolute.items] == ["keep"]
    assert absolute.items[0].reason == "no cuts found"
