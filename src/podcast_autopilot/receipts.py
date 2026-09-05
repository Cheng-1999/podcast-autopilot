from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .audit import sha256_of_file
from .config import AppConfig
from .ffmpeg import ffmpeg_version, measure_loudness
from .plan import EditPlan

RECEIPT_SCHEMA_ID = "podcast-autopilot.receipt/v1"


def write_receipt(
    plan: EditPlan,
    source_path: Path,
    plan_path: Path,
    output_path: Path,
    out_dir: Path,
    config: AppConfig | None = None,
) -> Path:
    source_path = Path(source_path)
    plan_path = Path(plan_path)
    output_path = Path(output_path)

    loudness = measure_loudness(output_path, config)

    receipt = {
        "schema": RECEIPT_SCHEMA_ID,
        "created": datetime.now(timezone.utc).isoformat(),
        "source": {
            "path": str(source_path),
            "sha256": sha256_of_file(source_path),
        },
        "plan": {
            "path": str(plan_path),
            "sha256": sha256_of_file(plan_path),
        },
        "output": {
            "path": str(output_path),
            "sha256": sha256_of_file(output_path),
        },
        "edit": {
            "seconds_removed": sum(item.end - item.start for item in plan.items if item.enabled and item.kind == "cut"),
            "predicted_duration": plan.predicted_duration,
        },
        "ffmpeg_version": ffmpeg_version(config),
        "loudness": {
            "input_i": float(loudness.get("input_i", "nan")),
            "input_tp": float(loudness.get("input_tp", "nan")),
            "input_lra": float(loudness.get("input_lra", "nan")),
            "input_thresh": float(loudness.get("input_thresh", "nan")),
        },
    }

    receipt_path = Path(out_dir) / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt_path
