from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path

from .plan import EditPlan

ALLOWED_KINDS = {"keep", "cut", "fade", "filler"}

# "filler" items are proposal annotations nested inside a "keep" span (a human
# flips enabled=true to turn one into an actual cut at apply time); they are
# exempt from the partition-style ordering/overlap check below, which only
# makes sense for kinds that tile the timeline.
PARTITION_KINDS = {"keep", "cut", "fade"}


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


def _effective_keep_spans(plan: EditPlan) -> list[tuple[float, float]]:
    """Spans a filler item may live in, mirroring how apply.py picks what to render.

    Explicit "keep" items win when present. A cut-only plan (the pause
    planner's output) has no keep items: apply.py derives the kept audio as
    the complement of the cuts, so the same complement is used here. All cut
    items count, enabled or not, so that toggling a cut can never make a
    previously valid filler proposal invalid (fail closed).
    """
    keeps = [(it.start, it.end) for it in plan.items if it.kind == "keep"]
    if keeps:
        return keeps
    spans: list[tuple[float, float]] = []
    cursor = 0.0
    for cut in sorted((it for it in plan.items if it.kind == "cut"), key=lambda it: it.start):
        if cut.start > cursor:
            spans.append((cursor, cut.start))
        cursor = max(cursor, cut.end)
    if cursor < plan.source.duration:
        spans.append((cursor, plan.source.duration))
    return spans


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
    # Only partition kinds (keep/cut/fade) are checked here; filler items
    # intentionally nest inside a keep item's span (see PARTITION_KINDS).
    partition_items = [it for it in plan.items if it.kind in PARTITION_KINDS]
    sorted_items = sorted(partition_items, key=lambda it: it.start)
    if [it.id for it in partition_items] != [it.id for it in sorted_items]:
        errors.append("items are not sorted by start time")

    for prev, curr in zip(sorted_items, sorted_items[1:]):
        if curr.start < prev.end:
            errors.append(
                f"items {prev.id} and {curr.id} overlap: "
                f"[{prev.start}, {prev.end}) vs [{curr.start}, {curr.end})"
            )

    # Filler proposals may not overlap each other, and each one must fall
    # fully inside some "keep" item: a filler cut can only trim audio that
    # would otherwise be kept, never expand what a "cut" item already removes.
    filler_items = [it for it in plan.items if it.kind == "filler"]
    sorted_fillers = sorted(filler_items, key=lambda it: it.start)
    for prev, curr in zip(sorted_fillers, sorted_fillers[1:]):
        if curr.start < prev.end:
            errors.append(
                f"filler items {prev.id} and {curr.id} overlap: "
                f"[{prev.start}, {prev.end}) vs [{curr.start}, {curr.end})"
            )

    keep_spans = _effective_keep_spans(plan)
    for filler in filler_items:
        if not any(ks <= filler.start and filler.end <= ke for ks, ke in keep_spans):
            errors.append(f"filler item {filler.id}: [{filler.start}, {filler.end}] is not inside any keep span")

    if errors:
        return AuditResult(ok=False, errors=errors)

    enabled_items = [item for item in plan.items if item.enabled]
    total_keep = sum(it.end - it.start for it in enabled_items if it.kind == "keep")
    # An enabled filler is rendered as a cut by apply.py, so it must count
    # toward the removal budget exactly like a "cut" item; otherwise a plan
    # could pass audit and still remove more audio than max_removed_fraction.
    total_cut = sum(it.end - it.start for it in enabled_items if it.kind in ("cut", "filler"))
    enabled_keeps = [it for it in enabled_items if it.kind == "keep"]
    total_keep -= sum(
        f.end - f.start
        for f in enabled_items
        if f.kind == "filler" and any(k.start <= f.start and f.end <= k.end for k in enabled_keeps)
    )
    max_fraction = plan.profile.max_removed_fraction
    if not math.isfinite(max_fraction) or max_fraction < 0 or max_fraction > 1:
        return AuditResult(ok=False, errors=[f"profile max_removed_fraction is invalid: {max_fraction}"])
    if duration <= 0 or (total_cut > 0 and total_cut / duration >= max_fraction):
        return AuditResult(
            ok=False,
            errors=[f"enabled cuts remove {total_cut / duration:.1%} of source; limit is < {max_fraction:.1%}"],
        )
    coverage_ratio = total_keep / duration if duration > 0 else 0.0

    return AuditResult(
        ok=True,
        errors=[],
        total_keep_duration=total_keep,
        total_cut_duration=total_cut,
        coverage_ratio=coverage_ratio,
    )
