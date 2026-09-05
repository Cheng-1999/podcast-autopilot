from __future__ import annotations

from pathlib import Path

from .config import AppConfig
from .ffmpeg import run_ffmpeg
from .plan import EditPlan, PlanItem


def _build_filter_complex(keep_items: list[PlanItem], crossfade_seconds: float) -> tuple[str, str]:
    parts: list[str] = []
    labels: list[str] = []
    for idx, item in enumerate(keep_items):
        label = f"seg{idx}"
        parts.append(f"[0:a]atrim=start={item.start:.6f}:end={item.end:.6f},asetpts=PTS-STARTPTS[{label}]")
        labels.append(label)

    if len(labels) == 1:
        return ";".join(parts), labels[0]

    current = labels[0]
    for idx in range(1, len(labels)):
        out_label = f"xf{idx}"
        parts.append(f"[{current}][{labels[idx]}]acrossfade=d={crossfade_seconds:.6f}[{out_label}]")
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

    configured_d = plan.render.crossfade_ms / 1000.0
    min_seg_duration = min(item.end - item.start for item in keep_items)
    crossfade_seconds = max(0.001, min(configured_d, min_seg_duration / 2))

    filter_complex, out_label = _build_filter_complex(keep_items, crossfade_seconds)

    args = [
        "-i", str(audio_path),
        "-filter_complex", filter_complex,
        "-map", f"[{out_label}]",
        str(output_path),
    ]
    run_ffmpeg(args, config)
    return output_path
