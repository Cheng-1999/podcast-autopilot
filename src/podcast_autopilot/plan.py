from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_ID = "podcast-autopilot.edit-plan/v1"


class SourceInfo(BaseModel):
    path: str
    sha256: str
    duration: float
    sr: int
    channels: int


class ProfileInfo(BaseModel):
    name: str
    sha256: str | None = None
    max_removed_fraction: float = 0.25


class PlanItem(BaseModel):
    """One edit-plan entry.

    `kind` is a plain string, not a closed enum: later tasks add filler,
    denoise, chapter and clip kinds without touching this schema. audit.py
    is the fail-closed gate that rejects kinds it doesn't recognize yet.
    """

    id: str
    kind: str
    start: float
    end: float
    reason: str = ""
    enabled: bool = True


class RenderSettings(BaseModel):
    crossfade_ms: int = 20
    sample_rate: int | None = None
    loudness_target_i: float = -16.0
    loudness_target_tp: float = -1.5


class EditPlan(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # Required and pinned: a plan missing "schema" or carrying any other id
    # (future v2, typo, foreign tool) is rejected at load time, fail closed.
    schema_id: str = Field(alias="schema")
    created: str
    source: SourceInfo
    profile: ProfileInfo
    items: list[PlanItem]
    render: RenderSettings = Field(default_factory=RenderSettings)
    predicted_duration: float | None = None

    @field_validator("schema_id")
    @classmethod
    def _check_schema_id(cls, value: str) -> str:
        if value != SCHEMA_ID:
            raise ValueError(f"unsupported edit-plan schema {value!r}; expected {SCHEMA_ID!r}")
        return value


def load_plan(path: Path) -> EditPlan:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return EditPlan.model_validate(data)


def save_plan(plan: EditPlan, path: Path) -> None:
    Path(path).write_text(plan.model_dump_json(by_alias=True, indent=2), encoding="utf-8")


def make_identity_keep_plan(source: SourceInfo, profile: ProfileInfo, created: str) -> EditPlan:
    """A single 'keep' item spanning the whole source, used by selftest."""
    item = PlanItem(id="item-0001", kind="keep", start=0.0, end=source.duration, reason="identity", enabled=True)
    return EditPlan(schema=SCHEMA_ID, created=created, source=source, profile=profile, items=[item])
