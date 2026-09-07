from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

from podcast_autopilot.ffmpeg import run_ffprobe_json


def test_ffprobe_decodes_non_cp1252_output_without_failing() -> None:
    completed = subprocess.CompletedProcess(
        ["ffprobe"],
        0,
        stdout='{"streams": [], "format": {"tags": {"title": "\ufffd"}}}',
        stderr="",
    )
    with mock.patch("podcast_autopilot.ffmpeg.resolve_ffmpeg_binaries", return_value=(Path("ffmpeg"), Path("ffprobe"))), mock.patch(
        "podcast_autopilot.ffmpeg.subprocess.run", return_value=completed
    ) as run:
        result = run_ffprobe_json(Path("upload.wav"))

    assert result["format"]["tags"]["title"] == "\ufffd"
    assert run.call_args.kwargs["encoding"] == "utf-8"
    assert run.call_args.kwargs["errors"] == "replace"
