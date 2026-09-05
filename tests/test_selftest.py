from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from podcast_autopilot.cli import app

runner = CliRunner()


def test_selftest_end_to_end(tmp_path: Path):
    result = runner.invoke(app, ["selftest", "--out-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "SELFTEST OK" in result.output
    assert any(tmp_path.rglob("*.edited.wav"))
