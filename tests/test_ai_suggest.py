from __future__ import annotations

import subprocess

import pytest

from podcast_autopilot.ai_suggest import AISuggestError, build_prompt, run_ai_suggest


def test_build_prompt_includes_timestamps_and_instructs_json_only():
    prompt = build_prompt(
        [{"start": 0.0, "end": 2.5, "text": "hello"}, {"start": 2.5, "end": 5.0, "text": "hello again, take two"}],
        duration=5.0,
    )
    assert "[0.00-2.50] hello" in prompt
    assert "JSON array" in prompt


def test_run_ai_suggest_parses_json_array(monkeypatch):
    def fake_run(command, input, capture_output, text, encoding, timeout):
        assert command == ["fake-cli", "-p"]
        return subprocess.CompletedProcess(
            command, 0, stdout='noise before\n[{"start": 1.0, "end": 2.0, "reason": "retake"}]\ntrailing', stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_ai_suggest(["fake-cli", "-p"], "prompt")
    assert len(result) == 1
    assert result[0].start == 1.0 and result[0].end == 2.0 and result[0].reason == "retake"


def test_run_ai_suggest_drops_malformed_entries_without_raising(monkeypatch):
    def fake_run(command, input, capture_output, text, encoding, timeout):
        return subprocess.CompletedProcess(command, 0, stdout='[{"start": "x"}, {"start": 1.0, "end": 2.0}]', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_ai_suggest(["fake-cli"], "prompt")
    assert len(result) == 1
    assert result[0].reason == "ai-suggested"


def test_run_ai_suggest_raises_on_missing_cli(monkeypatch):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(AISuggestError, match="not found"):
        run_ai_suggest(["nonexistent-cli"], "prompt")


def test_run_ai_suggest_raises_on_timeout(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="fake-cli", timeout=1.0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(AISuggestError, match="timed out"):
        run_ai_suggest(["fake-cli"], "prompt", timeout_s=1.0)


def test_run_ai_suggest_raises_on_nonzero_exit(monkeypatch):
    def fake_run(command, input, capture_output, text, encoding, timeout):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(AISuggestError, match="exited 1"):
        run_ai_suggest(["fake-cli"], "prompt")


def test_run_ai_suggest_raises_when_no_json_array_found(monkeypatch):
    def fake_run(command, input, capture_output, text, encoding, timeout):
        return subprocess.CompletedProcess(command, 0, stdout="I don't see anything worth cutting.", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(AISuggestError, match="did not return a JSON array"):
        run_ai_suggest(["fake-cli"], "prompt")


def test_run_ai_suggest_caps_suggestion_count(monkeypatch):
    entries = ", ".join(f'{{"start": {i}.0, "end": {i}.5, "reason": "x"}}' for i in range(30))

    def fake_run(command, input, capture_output, text, encoding, timeout):
        return subprocess.CompletedProcess(command, 0, stdout=f"[{entries}]", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_ai_suggest(["fake-cli"], "prompt")
    assert len(result) == 20
