from __future__ import annotations

from pathlib import Path

from podcast_autopilot.audit import audit_plan, sha256_of_file
from podcast_autopilot.ffmpeg import generate_synthetic_audio
from podcast_autopilot.plan import EditPlan, ProfileInfo, SourceInfo
from podcast_autopilot.transcribe import (
    Word,
    detect_fillers,
    filler_plan_items,
    transcribe_audio,
    write_markdown,
    write_srt,
)


def test_detects_isolated_filler_with_pauses_on_both_sides():
    words = [
        Word(word="今天", start=0.0, end=0.5, probability=0.9),
        Word(word="嗯", start=1.0, end=1.2, probability=0.8),
        Word(word="天氣", start=1.7, end=2.2, probability=0.9),
    ]
    candidates = detect_fillers(words, filler_words=["嗯"], pause_threshold_s=0.2, min_probability=0.5)
    assert len(candidates) == 1
    assert candidates[0]["word"] == "嗯"


def test_rejects_filler_glued_to_a_neighbor():
    words = [
        Word(word="今天", start=0.0, end=0.5, probability=0.9),
        Word(word="嗯", start=0.55, end=0.7, probability=0.8),
        Word(word="天氣", start=0.75, end=1.2, probability=0.9),
    ]
    assert detect_fillers(words, filler_words=["嗯"]) == []


def test_rejects_low_probability():
    words = [Word(word="嗯", start=1.0, end=1.2, probability=0.3)]
    assert detect_fillers(words, filler_words=["嗯"]) == []


def test_first_and_last_word_bordered_by_audio_edges_count_as_isolated():
    words = [Word(word="嗯", start=0.0, end=0.2, probability=0.9)]
    candidates = detect_fillers(words, filler_words=["嗯"])
    assert len(candidates) == 1


def test_non_filler_word_ignored():
    words = [Word(word="今天", start=0.0, end=0.5, probability=0.9)]
    assert detect_fillers(words, filler_words=["嗯"]) == []


def test_default_filler_word_list_used_when_not_specified():
    words = [Word(word="然後", start=1.0, end=1.3, probability=0.9)]
    candidates = detect_fillers(words)
    assert len(candidates) == 1
    assert candidates[0]["word"] == "然後"


def test_filler_plan_items_are_disabled_proposals():
    candidates = [{"word": "嗯", "start": 1.0, "end": 1.2, "probability": 0.8}]
    items = filler_plan_items(candidates)
    assert len(items) == 1
    item = items[0]
    assert item.kind == "filler"
    assert item.enabled is False
    assert item.start == 1.0 and item.end == 1.2


def test_filler_items_pass_audit_when_contained_in_a_keep_item(tmp_path: Path):
    audio_file = tmp_path / "source.bin"
    audio_file.write_bytes(b"not really audio, just needs stable bytes for a hash" * 100)
    source = SourceInfo(path=str(audio_file), sha256=sha256_of_file(audio_file), duration=10.0, sr=44100, channels=1)
    from podcast_autopilot.plan import PlanItem

    items = [
        PlanItem(id="a", kind="keep", start=0.0, end=10.0),
        PlanItem(id="filler-0001", kind="filler", start=1.0, end=1.2, enabled=False),
    ]
    plan = EditPlan(
        schema="podcast-autopilot.edit-plan/v1",
        created="2026-09-05T00:00:00+00:00",
        source=source,
        profile=ProfileInfo(name="test"),
        items=items,
    )
    result = audit_plan(plan, audio_file)
    assert result.ok, result.errors


def test_transcribe_smoke_produces_three_artifacts(tmp_path: Path):
    """Synthetic tone (no speech) should still transcribe without crashing."""
    source_path = tmp_path / "smoke_source.wav"
    generate_synthetic_audio(source_path, duration=30.0)

    data = transcribe_audio(source_path, model_size="tiny")
    assert data["schema"] == "podcast-autopilot.transcript/v1"

    target_dir = tmp_path / "out"
    target_dir.mkdir()
    write_srt(data["segments"], target_dir / "transcript.srt")
    write_markdown(data["segments"], target_dir / "transcript.md")
    from podcast_autopilot.transcribe import save_transcript

    save_transcript(data, target_dir / "transcript.json")

    assert (target_dir / "transcript.json").is_file()
    assert (target_dir / "transcript.srt").is_file()
    assert (target_dir / "transcript.md").is_file()
