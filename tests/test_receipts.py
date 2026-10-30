from __future__ import annotations

import json
from pathlib import Path

from podcast_autopilot.audit import sha256_of_file
from podcast_autopilot.ffmpeg import generate_synthetic_audio
from podcast_autopilot.plan import EditPlan, PlanItem, ProfileInfo, RenderSettings, SourceInfo
from podcast_autopilot.receipts import write_receipt


def test_write_receipt_counts_cut_and_filler_in_seconds_removed(tmp_path: Path):
    source_wav = tmp_path / "source.wav"
    output_wav = tmp_path / "output.wav"
    generate_synthetic_audio(source_wav, duration=5.0)
    generate_synthetic_audio(output_wav, duration=3.8)

    plan = EditPlan(
        schema="podcast-autopilot.edit-plan/v1",
        created="2026-09-07T00:00:00+00:00",
        source=SourceInfo(
            path=str(source_wav),
            sha256=sha256_of_file(source_wav),
            duration=5.0,
            sr=44100,
            channels=1,
        ),
        profile=ProfileInfo(name="test"),
        items=[
            # Enabled pause cut: 1.0s
            PlanItem(id="cut-0001", kind="cut", start=1.0, end=2.0, enabled=True),
            # Disabled pause cut: 0.5s (should not be counted)
            PlanItem(id="cut-0002", kind="cut", start=2.5, end=3.0, enabled=False),
            # Enabled filler cut: 0.2s
            PlanItem(id="filler-0001", kind="filler", start=3.2, end=3.4, enabled=True),
            # Disabled filler cut: 0.3s (should not be counted)
            PlanItem(id="filler-0002", kind="filler", start=4.0, end=4.3, enabled=False),
            # Keep item: should not be counted
            PlanItem(id="keep-0001", kind="keep", start=0.0, end=1.0, enabled=True),
        ],
        render=RenderSettings(),
        predicted_duration=3.8,
    )

    plan_path = tmp_path / "plan.json"
    plan_path.write_text(plan.model_dump_json(by_alias=True, indent=2), encoding="utf-8")

    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    receipt_path = write_receipt(plan, source_wav, plan_path, output_wav, out_dir)
    assert receipt_path.is_file()

    data = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert data["schema"] == "podcast-autopilot.receipt/v1"
    # seconds_removed should be exactly 1.0 (enabled cut) + 0.2 (enabled filler) = 1.2
    assert round(data["edit"]["seconds_removed"], 3) == 1.2
    assert data["edit"]["predicted_duration"] == 3.8
