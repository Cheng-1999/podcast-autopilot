from __future__ import annotations

from pathlib import Path

import pytest

from podcast_autopilot.audit import audit_plan, sha256_of_file
from podcast_autopilot.plan import EditPlan, PlanItem, ProfileInfo, SourceInfo


@pytest.fixture
def audio_file(tmp_path: Path) -> Path:
    path = tmp_path / "source.bin"
    path.write_bytes(b"not really audio, just needs stable bytes for a hash" * 100)
    return path


def _make_plan(source: SourceInfo, items: list[PlanItem]) -> EditPlan:
    return EditPlan(
        schema="podcast-autopilot.edit-plan/v1",
        created="2026-09-05T00:00:00+00:00",
        source=source,
        profile=ProfileInfo(name="test"),
        items=items,
    )


def test_valid_plan_passes(audio_file: Path):
    source = SourceInfo(path=str(audio_file), sha256=sha256_of_file(audio_file), duration=10.0, sr=44100, channels=1)
    items = [
        PlanItem(id="a", kind="keep", start=0.0, end=5.0),
        PlanItem(id="b", kind="keep", start=5.0, end=10.0),
    ]
    result = audit_plan(_make_plan(source, items), audio_file)
    assert result.ok, result.errors
    assert result.total_keep_duration == pytest.approx(10.0)


def test_rejects_overlap(audio_file: Path):
    source = SourceInfo(path=str(audio_file), sha256=sha256_of_file(audio_file), duration=10.0, sr=44100, channels=1)
    items = [
        PlanItem(id="a", kind="keep", start=0.0, end=6.0),
        PlanItem(id="b", kind="keep", start=5.0, end=10.0),
    ]
    result = audit_plan(_make_plan(source, items), audio_file)
    assert not result.ok
    assert any("overlap" in e for e in result.errors)


def test_rejects_out_of_range(audio_file: Path):
    source = SourceInfo(path=str(audio_file), sha256=sha256_of_file(audio_file), duration=10.0, sr=44100, channels=1)
    items = [PlanItem(id="a", kind="keep", start=0.0, end=15.0)]
    result = audit_plan(_make_plan(source, items), audio_file)
    assert not result.ok
    assert any("out of bounds" in e for e in result.errors)


def test_rejects_hash_mismatch(audio_file: Path):
    source = SourceInfo(path=str(audio_file), sha256="0" * 64, duration=10.0, sr=44100, channels=1)
    items = [PlanItem(id="a", kind="keep", start=0.0, end=10.0)]
    result = audit_plan(_make_plan(source, items), audio_file)
    assert not result.ok
    assert any("sha256 mismatch" in e for e in result.errors)


def test_rejects_unknown_kind(audio_file: Path):
    source = SourceInfo(path=str(audio_file), sha256=sha256_of_file(audio_file), duration=10.0, sr=44100, channels=1)
    items = [PlanItem(id="a", kind="teleport", start=0.0, end=10.0)]
    result = audit_plan(_make_plan(source, items), audio_file)
    assert not result.ok
    assert any("unknown kind" in e for e in result.errors)


def test_rejects_unsorted_items_even_when_disabled(audio_file: Path):
    source = SourceInfo(path=str(audio_file), sha256=sha256_of_file(audio_file), duration=10.0, sr=44100, channels=1)
    items = [
        PlanItem(id="b", kind="keep", start=5.0, end=10.0, enabled=False),
        PlanItem(id="a", kind="keep", start=0.0, end=5.0),
    ]
    result = audit_plan(_make_plan(source, items), audio_file)
    assert not result.ok
    assert any("not sorted" in e for e in result.errors)


def test_rejects_overlap_with_disabled_item(audio_file: Path):
    source = SourceInfo(path=str(audio_file), sha256=sha256_of_file(audio_file), duration=10.0, sr=44100, channels=1)
    items = [
        PlanItem(id="a", kind="keep", start=0.0, end=6.0),
        PlanItem(id="b", kind="cut", start=5.0, end=10.0, enabled=False),
    ]
    result = audit_plan(_make_plan(source, items), audio_file)
    assert not result.ok
    assert any("overlap" in e for e in result.errors)


def test_rejects_non_finite_start_or_end(audio_file: Path):
    source = SourceInfo(path=str(audio_file), sha256=sha256_of_file(audio_file), duration=10.0, sr=44100, channels=1)
    items = [PlanItem(id="a", kind="keep", start=float("nan"), end=float("inf"))]
    result = audit_plan(_make_plan(source, items), audio_file)
    assert not result.ok
    assert any("finite" in e for e in result.errors)


def test_disabled_items_excluded_from_coverage(audio_file: Path):
    source = SourceInfo(path=str(audio_file), sha256=sha256_of_file(audio_file), duration=10.0, sr=44100, channels=1)
    items = [
        PlanItem(id="a", kind="keep", start=0.0, end=5.0),
        PlanItem(id="b", kind="keep", start=5.0, end=10.0, enabled=False),
    ]
    result = audit_plan(_make_plan(source, items), audio_file)
    assert result.ok, result.errors
    assert result.total_keep_duration == pytest.approx(5.0)
    assert result.coverage_ratio == pytest.approx(0.5)


def test_enabled_filler_counts_toward_removal_limit(audio_file: Path):
    source = SourceInfo(path=str(audio_file), sha256=sha256_of_file(audio_file), duration=10.0, sr=44100, channels=1)
    items = [
        PlanItem(id="a", kind="keep", start=0.0, end=10.0),
        PlanItem(id="filler-0001", kind="filler", start=1.0, end=4.0, enabled=True),
    ]
    plan = _make_plan(source, items)
    plan.profile.max_removed_fraction = 0.25
    result = audit_plan(plan, audio_file)
    assert not result.ok
    assert any("remove" in e for e in result.errors)

    # Same plan with the proposal left disabled removes nothing.
    items[1].enabled = False
    result = audit_plan(plan, audio_file)
    assert result.ok, result.errors
    assert result.total_cut_duration == pytest.approx(0.0)
    assert result.total_keep_duration == pytest.approx(10.0)


def test_enabled_filler_is_reported_as_cut_duration(audio_file: Path):
    source = SourceInfo(path=str(audio_file), sha256=sha256_of_file(audio_file), duration=10.0, sr=44100, channels=1)
    items = [
        PlanItem(id="a", kind="keep", start=0.0, end=10.0),
        PlanItem(id="filler-0001", kind="filler", start=1.0, end=1.5, enabled=True),
    ]
    result = audit_plan(_make_plan(source, items), audio_file)
    assert result.ok, result.errors
    assert result.total_cut_duration == pytest.approx(0.5)
    assert result.total_keep_duration == pytest.approx(9.5)


def test_filler_in_cut_only_plan_must_sit_in_the_cut_complement(audio_file: Path):
    # Pause plans store only "cut" items; apply.py renders the complement, so
    # audit accepts fillers inside the complement and rejects ones overlapping a cut.
    source = SourceInfo(path=str(audio_file), sha256=sha256_of_file(audio_file), duration=10.0, sr=44100, channels=1)
    items = [
        PlanItem(id="cut-0001", kind="cut", start=4.0, end=5.0),
        PlanItem(id="filler-0001", kind="filler", start=1.0, end=1.2, enabled=False),
    ]
    result = audit_plan(_make_plan(source, items), audio_file)
    assert result.ok, result.errors

    items = [
        PlanItem(id="cut-0001", kind="cut", start=4.0, end=5.0, enabled=False),
        PlanItem(id="filler-0001", kind="filler", start=4.5, end=5.5, enabled=False),
    ]
    result = audit_plan(_make_plan(source, items), audio_file)
    assert not result.ok
    assert any("filler item filler-0001" in e for e in result.errors)
