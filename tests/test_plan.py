from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from podcast_autopilot.plan import SCHEMA_ID, EditPlan, load_plan

_BASE = {
    "created": "2026-09-05T00:00:00+00:00",
    "source": {"path": "x.wav", "sha256": "0" * 64, "duration": 10.0, "sr": 44100, "channels": 1},
    "profile": {"name": "test"},
    "items": [],
}


def test_accepts_expected_schema_id():
    plan = EditPlan.model_validate({**_BASE, "schema": SCHEMA_ID})
    assert plan.schema_id == SCHEMA_ID


def test_rejects_missing_schema_id():
    with pytest.raises(ValidationError):
        EditPlan.model_validate(dict(_BASE))


@pytest.mark.parametrize("bad", ["podcast-autopilot.edit-plan/v2", "some-other-tool/v1", ""])
def test_rejects_wrong_schema_id(bad: str):
    with pytest.raises(ValidationError, match="unsupported edit-plan schema"):
        EditPlan.model_validate({**_BASE, "schema": bad})


def test_load_plan_rejects_wrong_schema_on_disk(tmp_path: Path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({**_BASE, "schema": "nope/v9"}), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_plan(path)
