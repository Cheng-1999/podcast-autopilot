from __future__ import annotations

import os
from pathlib import Path

import pytest

from podcast_autopilot.config import AppConfig, FFmpegNotFoundError, resolve_binary, resolve_ffmpeg_binaries

EXE = ".exe" if os.name == "nt" else ""


@pytest.fixture
def fake_bin(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / f"ffmpeg{EXE}").write_bytes(b"")
    (bin_dir / f"ffprobe{EXE}").write_bytes(b"")
    return bin_dir


def test_ffmpeg_path_as_directory_resolves_both(fake_bin: Path):
    ffmpeg, ffprobe = resolve_ffmpeg_binaries(AppConfig(ffmpeg_path=str(fake_bin)))
    assert ffmpeg == fake_bin / f"ffmpeg{EXE}"
    assert ffprobe == fake_bin / f"ffprobe{EXE}"


def test_ffmpeg_path_as_ffmpeg_exe_resolves_sibling_ffprobe(fake_bin: Path):
    ffmpeg, ffprobe = resolve_ffmpeg_binaries(AppConfig(ffmpeg_path=str(fake_bin / f"ffmpeg{EXE}")))
    assert ffmpeg == fake_bin / f"ffmpeg{EXE}"
    assert ffprobe == fake_bin / f"ffprobe{EXE}"
    assert ffprobe.stem == "ffprobe"


def test_ffmpeg_path_exe_without_sibling_falls_through(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    lonely = tmp_path / f"ffmpeg{EXE}"
    lonely.write_bytes(b"")
    monkeypatch.setattr("podcast_autopilot.config.shutil.which", lambda name: None)
    monkeypatch.setattr("podcast_autopilot.config.DEFAULT_TOOLS_BIN", tmp_path / "nowhere")
    assert resolve_binary("ffmpeg", str(lonely)) == lonely
    with pytest.raises(FFmpegNotFoundError):
        resolve_binary("ffprobe", str(lonely))
