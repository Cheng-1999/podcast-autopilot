from __future__ import annotations

from pathlib import Path

import pytest

from podcast_autopilot.audit import audit_plan, sha256_of_file
from podcast_autopilot.clips import (
    build_candidates,
    generate_windows,
    merge_clip_items,
    render_clip,
    write_clip_srt,
)
from podcast_autopilot.config import AppConfig, ClipsConfig
from podcast_autopilot.ffmpeg import generate_synthetic_audio
from podcast_autopilot.plan import EditPlan, PlanItem, ProfileInfo, SourceInfo
from podcast_autopilot.probe import probe_audio


def _segment(idx: int, start: float, end: float, text: str) -> dict:
    return {"id": idx, "start": start, "end": end, "text": text, "words": []}


def _fabricated_transcript(keyword_text: str) -> dict:
    # 5 segments, 20s each, 1s pauses (well above the 0.4s threshold), so every
    # boundary between segments is a valid candidate start/end. Only segment 2
    # carries the keyword, repeated, with no question marks/numbers/capitalized
    # tokens/filler anywhere so keyword density is the only thing that varies.
    segments = [
        _segment(0, 0.0, 20.0, "今天的內容都很普通沒有重點也沒有數字"),
        _segment(1, 21.0, 41.0, "這裡也是普通的閒聊內容沒有特別之處"),
        _segment(2, 42.0, 62.0, keyword_text),
        _segment(3, 63.0, 83.0, "這段一樣是普通的閒聊沒有特別內容"),
        _segment(4, 84.0, 104.0, "最後一段也是普通內容沒有重點兩個字"),
    ]
    return {"schema": "podcast-autopilot.transcript/v1", "segments": segments}


def test_high_keyword_region_ranks_first():
    keyword_text = "重點重點重點重點重點：這段才是精華內容重點重點"
    transcript = _fabricated_transcript(keyword_text)
    config = AppConfig(clips=ClipsConfig(keywords=["重點"]), filler_words=[])

    candidates = build_candidates(transcript, config)
    assert candidates

    best = max(candidates, key=lambda c: c["score"])
    assert "重點重點重點" in best["text"]

    other_scores = [c["score"] for c in candidates if "重點重點重點" not in c["text"]]
    assert other_scores, "expected at least one candidate without the keyword region"
    assert all(best["score"] > s for s in other_scores)


def test_candidates_start_and_end_on_segment_boundaries():
    transcript = _fabricated_transcript("普通內容沒有重點")
    config = AppConfig(clips=ClipsConfig())
    candidates = build_candidates(transcript, config)
    assert candidates

    starts = {seg["start"] for seg in transcript["segments"]}
    ends = {seg["end"] for seg in transcript["segments"]}
    for c in candidates:
        assert c["start"] in starts, f"candidate start {c['start']} is not on a segment boundary"
        assert c["end"] in ends, f"candidate end {c['end']} is not on a segment boundary"
        assert 30.0 <= c["duration"] <= 90.0


def test_generate_windows_rejects_short_and_long_durations():
    transcript = _fabricated_transcript("普通內容")
    windows = generate_windows(transcript["segments"], pause_threshold_s=0.4, min_duration=30.0, max_duration=90.0)
    assert windows
    for _start, _end, duration in windows:
        assert 30.0 <= duration <= 90.0


def test_generate_windows_ignores_short_pauses():
    # A gap below the threshold must not become a usable boundary.
    segments = [
        _segment(0, 0.0, 30.0, "第一段"),
        _segment(1, 30.2, 65.0, "第二段"),  # 0.2s gap: below the 0.4s threshold
        _segment(2, 66.0, 96.0, "第三段"),  # 1.0s gap: a valid boundary
    ]
    windows = generate_windows(segments, pause_threshold_s=0.4, min_duration=30.0, max_duration=90.0)
    starts = {w[0] for w in windows}
    ends = {w[1] for w in windows}
    assert 1 not in starts  # segment 1 only follows a sub-threshold pause
    assert 0 not in ends  # segment 0 only precedes a sub-threshold pause


def test_audit_accepts_clip_kind(tmp_path: Path):
    audio_file = tmp_path / "source.bin"
    audio_file.write_bytes(b"not really audio, just needs stable bytes for a hash" * 100)
    source = SourceInfo(path=str(audio_file), sha256=sha256_of_file(audio_file), duration=100.0, sr=44100, channels=1)
    items = [
        PlanItem(id="a", kind="keep", start=0.0, end=100.0),
        PlanItem(id="clip-0001", kind="clip", start=10.0, end=60.0, reason="clip candidate score=1.23", enabled=False),
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
    # A disabled, always-non-partition "clip" item must not affect the removal budget.
    assert result.total_cut_duration == pytest.approx(0.0)
    assert result.total_keep_duration == pytest.approx(100.0)


def test_merge_clip_items_replaces_stale_proposals():
    existing = [
        PlanItem(id="a", kind="keep", start=0.0, end=100.0),
        PlanItem(id="clip-0001", kind="clip", start=1.0, end=31.0, reason="old", enabled=False),
    ]
    candidates = [{"id": "clip-0001", "start": 5.0, "end": 40.0, "score": 2.0}]
    merged = merge_clip_items(existing, candidates)
    clip_items = [it for it in merged if it.kind == "clip"]
    assert len(clip_items) == 1
    assert clip_items[0].start == 5.0
    assert clip_items[0].end == 40.0
    assert clip_items[0].enabled is False


def test_render_clip_duration_matches_window(tmp_path: Path):
    audio_path = tmp_path / "source.wav"
    generate_synthetic_audio(audio_path, duration=10.0)
    config = AppConfig()

    output_path = tmp_path / "clip.mp3"
    start, end = 2.0, 7.0
    render_clip(audio_path, start, end, output_path, config)

    assert output_path.is_file()
    info = probe_audio(output_path, config)
    delta = abs(info["duration"] - (end - start))
    assert delta <= 0.05, f"duration delta {delta * 1000:.1f}ms exceeds 50ms tolerance"


def test_render_clip_output_not_visible_until_render_completes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Regression for the intermittent "clip won't play" bug: ffmpeg creates+truncates
    its destination the instant it opens it, well before encoding finishes. If
    render_clip wrote straight to output_path, a request landing in that window (the
    API exposes a clip as soon as output_path exists) would stream a partial/silent
    MP3. render_clip must render to a same-directory temp file and only os.replace()
    it into place after ffmpeg exits successfully, and must not leak that temp file.
    """
    import podcast_autopilot.clips as clips_mod

    audio_path = tmp_path / "source.wav"
    generate_synthetic_audio(audio_path, duration=10.0)
    config = AppConfig()
    output_path = tmp_path / "clip.mp3"

    real_run_ffmpeg = clips_mod.run_ffmpeg
    output_path_existed_during_final_render = []

    def fake_run_ffmpeg(args, cfg=None):
        dest = Path(args[-1])
        if dest.suffix == ".mp3":
            output_path_existed_during_final_render.append(output_path.exists())
            dest.write_bytes(b"\x00" * 128)  # simulate ffmpeg's truncate-then-write
            return None
        return real_run_ffmpeg(args, cfg)

    monkeypatch.setattr(clips_mod, "run_ffmpeg", fake_run_ffmpeg)

    render_clip(audio_path, 2.0, 7.0, output_path, config)

    assert output_path_existed_during_final_render == [False]
    assert output_path.is_file()
    assert list(tmp_path.glob(".*tmp-*")) == []


def test_write_clip_srt_rebases_to_zero(tmp_path: Path):
    segments = [
        {"start": 0.0, "end": 5.0, "text": "before"},
        {"start": 10.0, "end": 15.0, "text": "inside"},
        {"start": 20.0, "end": 25.0, "text": "after"},
    ]
    srt_path = tmp_path / "clip.srt"
    write_clip_srt(segments, start=8.0, end=18.0, path=srt_path)
    content = srt_path.read_text(encoding="utf-8")
    assert "inside" in content
    assert "before" not in content
    assert "after" not in content
    assert "00:00:02,000 --> 00:00:07,000" in content
