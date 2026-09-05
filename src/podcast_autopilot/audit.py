from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path

from .plan import EditPlan

ALLOWED_KINDS = {"keep", "cut", "fade"}


@dataclass
class AuditResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    total_keep_duration: float = 0.0
    total_cut_duration: float = 0.0
    coverage_ratio: float = 0.0


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def audit_plan(plan: EditPlan, audio_path: Path) -> AuditResult:
    """Fail-closed validation of an edit plan against the audio file on disk.

    Any single problem (bad hash, unknown kind, out-of-range item, overlap,
    unsorted items) makes the whole plan unusable: ok=False and no partial
    coverage numbers.
    """
    errors: list[str] = []
    audio_path = Path(audio_path)

    if not audio_path.is_file():
        return AuditResult(ok=False, errors=[f"source audio not found: {audio_path}"])

    actual_sha256 = sha256_of_file(audio_path)
    if actual_sha256 != plan.source.sha256:
        errors.append(
            f"source sha256 mismatch: plan has {plan.source.sha256}, file on disk is {actual_sha256}"
        )

    duration = plan.source.duration

    for item in plan.items:
        if item.kind not in ALLOWED_KINDS:
            errors.append(f"item {item.id}: unknown kind '{item.kind}'")
        if not (math.isfinite(item.start) and math.isfinite(item.end)):
            # NaN/inf compare False against everything, so the range and
            # ordering checks below would silently pass a malformed item;
            # catch it here instead of falling through fail-open.
            errors.append(f"item {item.id}: start/end must be finite, got [{item.start}, {item.end}]")
            continue
        if item.end <= item.start:
            errors.append(f"item {item.id}: end ({item.end}) <= start ({item.start})")
        if item.start < 0 or item.end > duration:
            errors.append(
                f"item {item.id}: range [{item.start}, {item.end}] out of bounds [0, {duration}]"
            )

    # Ordering and overlap are contract-level properties of the whole plan:
    # disabled items must still be sorted and non-overlapping so that
    # toggling `enabled` can never turn a valid plan into an invalid one.
    sorted_items = sorted(plan.items, key=lambda it: it.start)
    if [it.id for it in plan.items] != [it.id for it in sorted_items]:
        errors.append("items are not sorted by start time")

    for prev, curr in zip(sorted_items, sorted_items[1:]):
        if curr.start < prev.end:
            errors.append(
                f"items {prev.id} and {curr.id} overlap: "
                f"[{prev.start}, {prev.end}) vs [{curr.start}, {curr.end})"
            )

    if errors:
        return AuditResult(ok=False, errors=errors)

    enabled_items = [item for item in plan.items if item.enabled]
    total_keep = sum(it.end - it.start for it in enabled_items if it.kind == "keep")
    total_cut = sum(it.end - it.start for it in enabled_items if it.kind == "cut")
    coverage_ratio = total_keep / duration if duration > 0 else 0.0

    return AuditResult(
        ok=True,
        errors=[],
        total_keep_duration=total_keep,
        total_cut_duration=total_cut,
        coverage_ratio=coverage_ratio,
    )
