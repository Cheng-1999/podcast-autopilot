from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from podcast_autopilot import transcribe as transcribe_mod
from podcast_autopilot.audit import audit_plan, sha256_of_file
from podcast_autopilot.cli import app
from podcast_autopilot.config import AppConfig
from podcast_autopilot.ffmpeg import generate_synthetic_audio
from podcast_autopilot.plan import EditPlan, ProfileInfo, SourceInfo
from podcast_autopilot.transcribe import Word, detect_fillers, filler_plan_items


class _FakeWord:
    def __init__(self, word: str, start: float, end: float, probability: float = 0.9):
        self.word = word
        self.start = start
        self.end = end
        self.probability = probability


class _FakeSegment:
    def __init__(self, text: str, start: float, end: float, words: list[_FakeWord]):
        self.text = text
        self.start = start
        self.end = end
        self.words = words


class _FakeInfo:
    def __init__(self, language: str, probability: float = 0.95):
        self.language = language
        self.language_probability = probability


class _FakeModel:
    """Stands in for WhisperModel: records transcribe() kwargs, never touches faster-whisper."""

    def __init__(self, detected_language: str, segment_text: str):
        self.detected_language = detected_language
        self.segment_text = segment_text
        self.transcribe_calls: list[dict] = []
        self.detect_language_called = False

    def detect_language(self, audio, vad_filter=True):
        self.detect_language_called = True
        return self.detected_language, 0.9, {}

    def transcribe(self, audio, **kwargs):
        self.transcribe_calls.append(kwargs)
        segs = [_FakeSegment(self.segment_text, 0.0, 1.0, [_FakeWord(self.segment_text, 0.0, 1.0)])]
        return iter(segs), _FakeInfo(kwargs["language"])


def _patch_transcribe_internals(monkeypatch, fake_model: _FakeModel):
    monkeypatch.setattr(transcribe_mod, "_load_model", lambda *a, **k: fake_model)
    monkeypatch.setattr("faster_whisper.audio.decode_audio", lambda path: "fake-audio-array")


def test_transcribe_audio_auto_detects_language_when_unset(monkeypatch, tmp_path: Path):
    fake_model = _FakeModel(detected_language="en", segment_text="hello world")
    _patch_transcribe_internals(monkeypatch, fake_model)

    result = transcribe_mod.transcribe_audio(tmp_path / "part.wav")

    assert fake_model.detect_language_called is True
    assert fake_model.transcribe_calls[0]["language"] == "en"
    assert fake_model.transcribe_calls[0]["initial_prompt"] is None
    assert result["language"] == "en"
    assert result["segments"][0].text == "hello world"  # untouched: no opencc pass for non-Chinese
    assert result["opencc_chars_changed"] == 0


def test_transcribe_audio_honors_explicit_language_without_detection(monkeypatch, tmp_path: Path):
    fake_model = _FakeModel(detected_language="ja", segment_text="hello")
    _patch_transcribe_internals(monkeypatch, fake_model)

    transcribe_mod.transcribe_audio(tmp_path / "part.wav", language="en")

    assert fake_model.detect_language_called is False
    assert fake_model.transcribe_calls[0]["language"] == "en"


def test_transcribe_audio_falls_back_to_config_language(monkeypatch, tmp_path: Path):
    fake_model = _FakeModel(detected_language="ja", segment_text="hello")
    _patch_transcribe_internals(monkeypatch, fake_model)

    transcribe_mod.transcribe_audio(tmp_path / "part.wav", config=AppConfig(whisper_language="ko"))

    assert fake_model.detect_language_called is False
    assert fake_model.transcribe_calls[0]["language"] == "ko"


def test_transcribe_audio_applies_opencc_and_prompt_only_for_chinese(monkeypatch, tmp_path: Path):
    fake_model = _FakeModel(detected_language="zh", segment_text="国际")  # simplified: expect s2twp to convert it
    _patch_transcribe_internals(monkeypatch, fake_model)

    result = transcribe_mod.transcribe_audio(tmp_path / "part.wav")

    assert fake_model.transcribe_calls[0]["initial_prompt"] == transcribe_mod.INITIAL_PROMPT_ZH_TW
    assert result["segments"][0].text != "国际"  # opencc s2twp pass changed it
    assert result["opencc_chars_changed"] > 0


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


def test_detect_fillers_applies_pre_roll_and_post_roll_padding():
    words = [
        Word(word="今天", start=0.0, end=0.5, probability=0.9),
        Word(word="嗯", start=1.0, end=1.2, probability=0.8),
        Word(word="天氣", start=1.8, end=2.2, probability=0.9),
    ]
    # pre_roll 0.2s: start 1.0 -> 0.8; post_roll 0.1s: end 1.2 -> 1.3
    cands = detect_fillers(words, filler_words=["嗯"], pre_roll_s=0.2, post_roll_s=0.1, guard_s=0.05)
    assert len(cands) == 1
    assert cands[0]["start"] == 0.8
    assert cands[0]["end"] == 1.3

    # pre_roll bounded by previous word end + guard (0.5 + 0.05 = 0.55)
    cands_clamped = detect_fillers(words, filler_words=["嗯"], pre_roll_s=0.8, post_roll_s=0.8, guard_s=0.05)
    assert len(cands_clamped) == 1
    assert cands_clamped[0]["start"] == 0.55
    assert cands_clamped[0]["end"] == 1.75


def test_detect_fillers_with_audio_snaps_to_energy_onset(tmp_path: Path):
    import numpy as np
    import scipy.io.wavfile as wavfile

    sr = 16000
    duration = 3.0
    audio = np.zeros(int(duration * sr), dtype=np.float32)
    # Speech tone between 1.1s and 1.8s
    t = np.arange(int(1.1 * sr), int(1.8 * sr)) / sr
    audio[int(1.1 * sr) : int(1.8 * sr)] = 0.2 * np.sin(2 * np.pi * 440 * t)

    audio_path = tmp_path / "filler_speech.wav"
    wavfile.write(str(audio_path), sr, audio)

    # Whisper reported word lagging at 1.4 - 1.8 (missed 1.1 - 1.4)
    words = [
        Word(word="今天", start=0.0, end=0.5, probability=0.9),
        Word(word="然後", start=1.4, end=1.8, probability=0.85),
        Word(word="天氣", start=2.4, end=2.8, probability=0.9),
    ]

    cands = detect_fillers(words, filler_words=["然後"], audio_path=audio_path, guard_s=0.05)
    assert len(cands) == 1
    # Onset should snap back close to 1.1s (e.g. 1.08 - 1.15) instead of lagging at 1.4s
    assert cands[0]["start"] < 1.15
    assert cands[0]["start"] >= 0.55


