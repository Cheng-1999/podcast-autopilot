from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from podcast_autopilot.cli import app
from podcast_autopilot.ffmpeg import generate_synthetic_audio

runner = CliRunner()


def _make_audio(tmp_path: Path) -> Path:
    audio_path = tmp_path / "src.wav"
    generate_synthetic_audio(audio_path, duration=1.0)
    return audio_path


def test_transcribe_rejects_invalid_model_size(tmp_path: Path):
    audio_path = _make_audio(tmp_path)
    result = runner.invoke(app, ["transcribe", str(audio_path), "--model", "large", "--out-dir", str(tmp_path)])
    assert result.exit_code != 0
    assert "small" in result.output and "medium" in result.output


def test_plan_fillers_rejects_invalid_model_size(tmp_path: Path):
    audio_path = _make_audio(tmp_path)
    result = runner.invoke(app, ["plan-fillers", str(audio_path), "--model", "large", "--out-dir", str(tmp_path)])
    assert result.exit_code != 0
    assert "small" in result.output and "medium" in result.output
