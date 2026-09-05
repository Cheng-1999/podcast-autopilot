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
