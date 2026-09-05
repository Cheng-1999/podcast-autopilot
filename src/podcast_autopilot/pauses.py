"""Silence detection and non-destructive pause-tightening edit plans."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from .audit import audit_plan, sha256_of_file
from .config import AppConfig, PauseConfig
from .ffmpeg import run_ffmpeg, run_ffprobe_json
from .plan import EditPlan, PlanItem, ProfileInfo, SourceInfo, SCHEMA_ID, save_plan
from .probe import probe_audio

_TIMESTAMP = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
_START = re.compile(rf"silence_start:\s*({_TIMESTAMP})")
_END = re.compile(rf"silence_end:\s*({_TIMESTAMP})")


def detect_silences(audio_path: Path, config: AppConfig | None = None) -> list[tuple[float, float]]:
    config = config or AppConfig()
    pauses = config.pauses or PauseConfig()
    ffmpeg_args = ["-i", str(audio_path), "-af", f"silencedetect=noise={pauses.noise}:d={pauses.min_duration:g}", "-f", "null", "-"]
    result = run_ffmpeg(ffmpeg_args, config)
    text = result.stderr
    events = sorted(
        [(m.start(), "start", float(m.group(1))) for m in _START.finditer(text)]
        + [(m.start(), "end", float(m.group(1))) for m in _END.finditer(text)],
    )
    silences: list[tuple[float, float]] = []
    active: float | None = None
    for _, kind, value in events:
        if kind == "start":
            active = value
        elif active is not None and value > active:
            silences.append((active, value))
            active = None
    if active is not None:
        raw_duration = run_ffprobe_json(audio_path, config).get("format", {}).get("duration")
        if raw_duration is not None and float(raw_duration) > active:
            silences.append((active, float(raw_duration)))
    return silences


def _candidate_cuts(silences: list[tuple[float, float]], duration: float, p: PauseConfig) -> list[tuple[float, float, float]]:
    candidates: list[tuple[float, float, float, bool, bool]] = []
    for start, end in silences:
        length = end - start
        if length <= p.max_keep:
            continue
        if start <= 0.001:  # Preserve the requested head, including the usual 0.3s.
            cut_start, cut_end = min(end, max(0.0, p.head, p.guard)), end
        elif end >= duration - 0.001:  # Preserve the requested tail.
            cut_start, cut_end = start, max(start, duration - max(0.0, p.tail, p.guard))
        else:
            keep_gap = max(0.0, p.target, 2 * p.guard)
            cut_start = start + keep_gap / 2
            cut_end = end - keep_gap / 2
        cut_start = max(start, cut_start)
        cut_end = min(end, cut_end)
        if cut_end > cut_start:
            candidates.append((cut_start, cut_end, length, start <= 0.001, end >= duration - 0.001))

    # A cut must not strand a tiny output segment. Leading/trailing policy is
    # intentionally allowed to be below min_segment (head defaults to .3s).
    accepted: list[tuple[float, float, float, bool, bool]] = []
    for index, candidate in enumerate(candidates):
        start, end, length, leading, trailing = candidate
        previous_end = candidates[index - 1][1] if index else 0.0
        next_start = candidates[index + 1][0] if index + 1 < len(candidates) else duration
        # Check the actual keep spans created by the complement renderer. The
        # old absolute-position check missed short speech spans between two
        # otherwise valid cuts.
        before_ok = start - previous_end >= p.min_segment
        after_ok = next_start - end >= p.min_segment
        if (before_ok or leading) and (after_ok or trailing):
            accepted.append(candidate)
        # Leading/trailing policies intentionally allow head/tail below
        # min_segment (the defaults are 0.3s and 1.0s respectively).
    return accepted


def build_pause_plan(audio_path: Path, config: AppConfig | None = None) -> EditPlan:
    config = config or AppConfig()
    info = probe_audio(audio_path, config)
    p = config.pauses or PauseConfig()
    cuts = _candidate_cuts(detect_silences(audio_path, config), info["duration"], p)
    items = [PlanItem(id=f"cut-{idx:04d}", kind="cut", start=start, end=end,
                      reason=f"pause {length:.2f}s -> {length - (end-start):.2f}s", enabled=True)
             for idx, (start, end, length, _leading, _trailing) in enumerate(cuts, 1)]
    source = SourceInfo(path=str(audio_path), sha256=sha256_of_file(audio_path), duration=info["duration"],
                        sr=info["sr"], channels=info["channels"])
    profile = ProfileInfo(name=config.profile_name, max_removed_fraction=p.max_removed_fraction)
    crossfade = 0.02
    predicted = info["duration"] - sum(item.end-item.start for item in items)
    if items:
        predicted -= crossfade * len(items)  # complement yields one join per cut
    plan = EditPlan(schema=SCHEMA_ID, created=datetime.now(timezone.utc).isoformat(), source=source,
                    profile=profile, items=items, predicted_duration=max(0.0, predicted))
    result = audit_plan(plan, audio_path)
    if not result.ok:
        raise ValueError("pause plan failed audit: " + "; ".join(result.errors))
    return plan


def write_pause_plan(audio_path: Path, out_dir: Path = Path("out"), config: AppConfig | None = None) -> tuple[Path, EditPlan]:
    plan = build_pause_plan(Path(audio_path), config)
    path = Path(out_dir) / Path(audio_path).stem / "plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    save_plan(plan, path)
    return path, plan
