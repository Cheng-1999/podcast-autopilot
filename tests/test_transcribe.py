from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from podcast_autopilot.audit import audit_plan, sha256_of_file
from podcast_autopilot.cli import app
from podcast_autopilot.ffmpeg import generate_synthetic_audio
from podcast_autopilot.plan import EditPlan, ProfileInfo, SourceInfo
from podcast_autopilot.transcribe import Word, detect_fillers, filler_plan_items


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


def test_first_and_last_word_are_never_proposed_without_pauses_on_both_sides():
    # No neighbour on one side means a pause there cannot be measured, so the
    # "pause > threshold on both sides" rule fails closed for edge words.
    assert detect_fillers([Word(word="嗯", start=0.0, end=0.2, probability=0.9)], filler_words=["嗯"]) == []
    words = [
        Word(word="嗯", start=0.0, end=0.2, probability=0.9),
        Word(word="今天", start=1.0, end=1.5, probability=0.9),
        Word(word="嗯", start=2.0, end=2.2, probability=0.9),
    ]
    assert detect_fillers(words, filler_words=["嗯"]) == []


def test_prompt_uses_only_full_width_punctuation():
    from podcast_autopilot.transcribe import INITIAL_PROMPT_ZH_TW

    ascii_punct = [c for c in INITIAL_PROMPT_ZH_TW if ord(c) < 128 and not c.isalnum()]
    assert ascii_punct == []


def test_non_filler_word_ignored():
    words = [Word(word="今天", start=0.0, end=0.5, probability=0.9)]
    assert detect_fillers(words, filler_words=["嗯"]) == []


def test_default_filler_word_list_used_when_not_specified():
    words = [
        Word(word="今天", start=0.0, end=0.5, probability=0.9),
        Word(word="然後", start=1.0, end=1.3, probability=0.9),
        Word(word="天氣", start=1.8, end=2.2, probability=0.9),
    ]
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
    """Synthetic tone (no speech) should still transcribe without crashing, via the real CLI command."""
    source_path = tmp_path / "smoke_source.wav"
    generate_synthetic_audio(source_path, duration=30.0)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["transcribe", str(source_path), "--model", "small", "--out-dir", str(tmp_path / "out")],
    )
    assert result.exit_code == 0, result.output

    target_dir = tmp_path / "out" / source_path.stem
    assert (target_dir / "transcript.json").is_file()
    assert (target_dir / "transcript.srt").is_file()
    assert (target_dir / "transcript.md").is_file()


def _cands(*spans):
    return [{"word": "嗯", "start": a, "end": b, "probability": 0.8} for a, b in spans]


def test_merge_filler_items_is_idempotent():
    from podcast_autopilot.plan import PlanItem
    from podcast_autopilot.transcribe import merge_filler_items

    base = [PlanItem(id="a", kind="keep", start=0.0, end=10.0)]
    once = merge_filler_items(base, _cands((1.0, 1.2), (5.0, 5.3)))
    twice = merge_filler_items(once, _cands((1.0, 1.2), (5.0, 5.3)))
    assert [(it.id, it.kind, it.start, it.end, it.enabled) for it in once] == [
        (it.id, it.kind, it.start, it.end, it.enabled) for it in twice
    ]
    assert sum(it.kind == "filler" for it in twice) == 2
    assert [it.id for it in twice if it.kind == "filler"] == ["filler-0001", "filler-0002"]


def test_merge_filler_items_preserves_human_enabled_and_drops_stale_proposals():
    from podcast_autopilot.plan import PlanItem
    from podcast_autopilot.transcribe import merge_filler_items

    existing = [
        PlanItem(id="a", kind="keep", start=0.0, end=10.0),
        PlanItem(id="filler-0001", kind="filler", start=1.0, end=1.2, enabled=True),
        PlanItem(id="filler-0002", kind="filler", start=3.0, end=3.2, enabled=False),
        PlanItem(id="filler-0003", kind="filler", start=5.0, end=5.3, enabled=True),
    ]
    # New detection: 0001 still matches, 0002 is gone, 0003 is gone, one new at 7.0.
    merged = merge_filler_items(existing, _cands((1.0, 1.2), (7.0, 7.1)))
    fillers = {it.id: it for it in merged if it.kind == "filler"}
    assert set(fillers) == {"filler-0001", "filler-0003", "filler-0004"}
    assert fillers["filler-0001"].enabled is True  # matched: human decision kept
    assert fillers["filler-0003"].enabled is True  # unmatched but enabled: kept
    assert fillers["filler-0004"].enabled is False and fillers["filler-0004"].start == 7.0
    assert [it.kind for it in merged if it.kind != "filler"] == ["keep"]
    assert [it.start for it in merged] == sorted(it.start for it in merged)


def test_merge_filler_items_filters_candidates_outside_keep_spans():
    from podcast_autopilot.plan import PlanItem
    from podcast_autopilot.transcribe import merge_filler_items

    base = [PlanItem(id="a", kind="keep", start=0.0, end=10.0)]
    # Candidates: (1.0, 1.2) is inside keep span [0.0, 5.0], but (7.0, 7.3) is outside.
    keep_spans = [(0.0, 5.0)]
    merged = merge_filler_items(base, _cands((1.0, 1.2), (7.0, 7.3)), keep_spans=keep_spans)
    fillers = [it for it in merged if it.kind == "filler"]
    assert len(fillers) == 1
    assert fillers[0].start == 1.0 and fillers[0].end == 1.2

