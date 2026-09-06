"""probe_audio must emit the contract field names: codec, sr, channels, sample_fmt, duration + loudness."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

from podcast_autopilot import probe as probe_mod

PROBE_KEYS = {"codec", "sr", "channels", "sample_fmt", "duration", "input_i", "input_tp", "input_lra", "input_thresh"}


def test_probe_uses_contract_field_names() -> None:
    fake_ffprobe = {
        "streams": [{"codec_type": "audio", "codec_name": "pcm_f32le", "sample_rate": "44100", "channels": 1, "sample_fmt": "flt"}],
        "format": {"duration": "1200.5"},
    }
    fake_loudness = {"input_i": "-23.1", "input_tp": "-3.2", "input_lra": "7.5", "input_thresh": "-33.4"}
    with mock.patch.object(probe_mod, "run_ffprobe_json", return_value=fake_ffprobe), mock.patch.object(
        probe_mod, "measure_loudness", return_value=fake_loudness
    ):
        info = probe_mod.probe_audio(Path("fake.wav"))

    assert PROBE_KEYS <= set(info)
    assert "codec_name" not in info and "sample_rate" not in info
    assert info["codec"] == "pcm_f32le"
    assert info["sr"] == 44100
    assert info["channels"] == 1
    assert info["sample_fmt"] == "flt"
    assert info["duration"] == 1200.5
    assert info["input_i"] == -23.1


def test_probe_audio_format_skips_loudness_measurement() -> None:
    fake_ffprobe = {
        "streams": [{"codec_type": "audio", "codec_name": "pcm_f32le", "sample_rate": "44100", "channels": 2, "sample_fmt": "flt"}],
        "format": {"duration": "600.0"},
    }
    with mock.patch.object(probe_mod, "run_ffprobe_json", return_value=fake_ffprobe), mock.patch.object(
        probe_mod, "measure_loudness"
    ) as mock_loudness:
        info = probe_mod.probe_audio_format(Path("fast.wav"))
        mock_loudness.assert_not_called()

    assert info["codec"] == "pcm_f32le"
    assert info["sr"] == 44100
    assert info["channels"] == 2
    assert info["duration"] == 600.0
    assert "input_i" not in info

