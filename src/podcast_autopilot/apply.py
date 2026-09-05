from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig
from .ffmpeg import run_ffmpeg
from .plan import EditPlan, PlanItem

FILLER_CROSSFADE_SECONDS = 0.015


@dataclass
class _RenderSegment:
    start: float
    end: float
    # True when this segment's start boundary was created by carving an
    # enabled filler cut out of a keep item, rather than being an original
    # plan boundary; the join before it then uses FILLER_CROSSFADE_SECONDS
    # instead of the plan's configured crossfade.
    fade_before: bool = False


def _carve_filler_cuts(keep_items: list[PlanItem], filler_items: list[PlanItem]) -> list[_RenderSegment]:
    """Cut enabled filler items out of the keep items that contain them.

    audit_plan() already guarantees every filler item lies fully inside some
    keep item and that filler items don't overlap each other.
    """
    enabled_fillers = sorted((f for f in filler_items if f.enabled), key=lambda f: f.start)
    segments: list[_RenderSegment] = []
    for keep in sorted(keep_items, key=lambda it: it.start):
        cursor = keep.start
        fade_before = False
        inside = [f for f in enabled_fillers if f.start >= keep.start and f.end <= keep.end]
        for filler in inside:
            if filler.start > cursor:
                segments.append(_RenderSegment(cursor, filler.start, fade_before=fade_before))
                fade_before = True
            cursor = max(cursor, filler.end)
        if keep.end > cursor:
            segments.append(_RenderSegment(cursor, keep.end, fade_before=fade_before))
    return segments


def _build_filter_complex(segments: list[_RenderSegment], crossfade_seconds: float) -> tuple[str, str]:
    parts: list[str] = []
    labels: list[str] = []
    for idx, seg in enumerate(segments):
        label = f"seg{idx}"
        parts.append(f"[0:a]atrim=start={seg.start:.6f}:end={seg.end:.6f},asetpts=PTS-STARTPTS[{label}]")
        labels.append(label)

    if len(labels) == 1:
        return ";".join(parts), labels[0]

    current = labels[0]
    for idx in range(1, len(labels)):
        base_d = FILLER_CROSSFADE_SECONDS if segments[idx].fade_before else crossfade_seconds
        min_seg_duration = min(segments[idx - 1].end - segments[idx - 1].start, segments[idx].end - segments[idx].start)
        d = max(0.001, min(base_d, min_seg_duration / 2))
        out_label = f"xf{idx}"
        parts.append(f"[{current}][{labels[idx]}]acrossfade=d={d:.6f}[{out_label}]")
        current = out_label
    return ";".join(parts), current


def apply_plan(plan: EditPlan, audio_path: Path, out_dir: Path, config: AppConfig | None = None) -> Path:
    """Render the plan's enabled 'keep' segments to <out_dir>/<stem>/<stem>.edited.wav.

    Segments are joined with a short acrossfade (plan.render.crossfade_ms) at
    each join. Assumes audit_plan() has already passed for this plan.
    """
    audio_path = Path(audio_path)
    stem = audio_path.stem
    target_dir = Path(out_dir) / stem
    target_dir.mkdir(parents=True, exist_ok=True)
    output_path = target_dir / f"{stem}.edited.wav"

    cuts = sorted((item for item in plan.items if item.enabled and item.kind == "cut"), key=lambda it: it.start)
    if cuts:
        keep_items = []
        cursor = 0.0
        for cut in cuts:
            if cut.start > cursor:
                keep_items.append(PlanItem(id=f"derived-{len(keep_items)}", kind="keep", start=cursor, end=cut.start))
            cursor = cut.end
        if cursor < plan.source.duration:
            keep_items.append(PlanItem(id=f"derived-{len(keep_items)}", kind="keep", start=cursor, end=plan.source.duration))
    else:
        keep_items = sorted((item for item in plan.items if item.enabled and item.kind == "keep"), key=lambda it: it.start)
    if not keep_items:
        raise ValueError("plan has no enabled 'keep' items to render")

    filler_items = [item for item in plan.items if item.kind == "filler"]
    segments = _carve_filler_cuts(keep_items, filler_items)
    if not segments:
        raise ValueError("plan has no audio left to render after filler cuts")

    configured_d = plan.render.crossfade_ms / 1000.0
    filter_complex, out_label = _build_filter_complex(segments, configured_d)

    args = [
        "-i", str(audio_path),
        "-filter_complex", filter_complex,
        "-map", f"[{out_label}]",
        str(output_path),
    ]
    run_ffmpeg(args, config)
    return output_path
