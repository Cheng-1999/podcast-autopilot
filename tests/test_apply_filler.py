from __future__ import annotations

from podcast_autopilot.apply import FILLER_CROSSFADE_SECONDS, _carve_filler_cuts
from podcast_autopilot.plan import PlanItem


def test_disabled_filler_leaves_keep_segment_untouched():
    keep = [PlanItem(id="a", kind="keep", start=0.0, end=10.0)]
    filler = [PlanItem(id="f1", kind="filler", start=4.0, end=4.2, enabled=False)]
    segments = _carve_filler_cuts(keep, filler)
    assert len(segments) == 1
    assert segments[0].start == 0.0 and segments[0].end == 10.0


def test_enabled_filler_splits_keep_segment_and_marks_fade_boundary():
    keep = [PlanItem(id="a", kind="keep", start=0.0, end=10.0)]
    filler = [PlanItem(id="f1", kind="filler", start=4.0, end=4.2, enabled=True)]
    segments = _carve_filler_cuts(keep, filler)
    assert len(segments) == 2
    assert (segments[0].start, segments[0].end) == (0.0, 4.0)
    assert (segments[1].start, segments[1].end) == (4.2, 10.0)
    assert segments[0].fade_before is False
    assert segments[1].fade_before is True
    assert FILLER_CROSSFADE_SECONDS == 0.015


def test_multiple_enabled_fillers_in_one_keep_item():
    keep = [PlanItem(id="a", kind="keep", start=0.0, end=10.0)]
    filler = [
        PlanItem(id="f1", kind="filler", start=2.0, end=2.2, enabled=True),
        PlanItem(id="f2", kind="filler", start=6.0, end=6.3, enabled=True),
    ]
    segments = _carve_filler_cuts(keep, filler)
    assert [(s.start, s.end) for s in segments] == [(0.0, 2.0), (2.2, 6.0), (6.3, 10.0)]
    assert [s.fade_before for s in segments] == [False, True, True]


def test_carve_filler_cuts_with_padding():
    keep = [PlanItem(id="a", kind="keep", start=1.0, end=9.0)]
    filler = [PlanItem(id="f1", kind="filler", start=4.0, end=4.2, enabled=True)]
    # With padding: start 4.0 - 0.2 = 3.8, end 4.2 + 0.1 = 4.3
    segments = _carve_filler_cuts(keep, filler, padding_start_s=0.2, padding_end_s=0.1)
    assert len(segments) == 2
    assert (segments[0].start, round(segments[0].end, 3)) == (1.0, 3.8)
    assert (round(segments[1].start, 3), segments[1].end) == (4.3, 9.0)

    # Padding clamped to cursor and keep.end: cut covers [1.0, 9.0] entirely, leaving 0 segments
    filler_edge = [PlanItem(id="f_edge", kind="filler", start=1.1, end=8.9, enabled=True)]
    segments_clamped = _carve_filler_cuts(keep, filler_edge, padding_start_s=0.5, padding_end_s=0.5)
    assert len(segments_clamped) == 0


def test_apply_plan_no_enabled_keeps_fallback_renders_full_audio(tmp_path):
    from podcast_autopilot.apply import apply_plan
    from podcast_autopilot.audit import sha256_of_file
    from podcast_autopilot.ffmpeg import generate_synthetic_audio
    from podcast_autopilot.plan import EditPlan, ProfileInfo, RenderSettings, SourceInfo

    audio_path = tmp_path / "test_fallback.wav"
    generate_synthetic_audio(audio_path, duration=2.0)

    # Plan with cuts all disabled and no explicit keep items
    plan = EditPlan(
        schema="podcast-autopilot.edit-plan/v1",
        created="2026-09-07T00:00:00+00:00",
        source=SourceInfo(
            path=str(audio_path),
            sha256=sha256_of_file(audio_path),
            duration=2.0,
            sr=44100,
            channels=1,
        ),
        profile=ProfileInfo(name="test"),
        items=[
            PlanItem(id="cut-0001", kind="cut", start=0.5, end=1.0, enabled=False),
        ],
        render=RenderSettings(),
    )

    out_dir = tmp_path / "out"
    out_file = apply_plan(plan, audio_path, out_dir)
    assert out_file.is_file()

