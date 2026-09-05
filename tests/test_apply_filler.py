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
