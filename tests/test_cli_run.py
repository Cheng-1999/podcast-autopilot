from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from podcast_autopilot.cli import app
from podcast_autopilot.ffmpeg import generate_synthetic_audio

runner = CliRunner()

REAL_REPORT_TEXT = "# real run\n"


def _make_episode(tmp_path: Path) -> Path:
    for name in ("part1.wav", "part2.wav"):
        generate_synthetic_audio(tmp_path / name, duration=2.0)
    episode_yaml = tmp_path / "episode.yaml"
    episode_yaml.write_text(
        yaml.safe_dump({"title": "T", "episode": 1, "parts": ["part1.wav", "part2.wav"]}), encoding="utf-8"
    )
    return episode_yaml


def test_run_dry_run_writes_its_own_report_and_keeps_the_real_one(tmp_path: Path):
    """`--dry-run` is a preview: it must not overwrite RUN_REPORT.md from the last
    real run (whose per-stage timings cannot be rebuilt from the cache)."""
    episode_yaml = _make_episode(tmp_path)
    out_dir = tmp_path / "out"
    real_report = out_dir / "episode" / "RUN_REPORT.md"
    real_report.parent.mkdir(parents=True)
    real_report.write_text(REAL_REPORT_TEXT, encoding="utf-8")

    result = runner.invoke(app, ["run", str(episode_yaml), "--dry-run", "--out-dir", str(out_dir)])
    assert result.exit_code == 0, result.output

    assert real_report.read_text(encoding="utf-8") == REAL_REPORT_TEXT
    preview = out_dir / "episode" / "RUN_REPORT.dry-run.md"
    assert preview.is_file()
    assert "dry run" in preview.read_text(encoding="utf-8")
    assert str(preview) in result.output
