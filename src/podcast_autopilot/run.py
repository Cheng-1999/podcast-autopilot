"""Episode `run` orchestration: probe -> clean -> plan-pauses -> transcribe ->
plan-fillers -> audit -> apply per part, then assemble.

Each stage's outputs are cached under a per-part `stage_cache.json`, keyed on
(source sha256, profile sha256, stage version) as described in the README.
"source" here means the actual file(s) a stage reads (e.g. plan.json + the
cleaned audio for `audit`/`apply`), so editing plan.json by hand -- the
Streamlit "apply again" flow -- invalidates only audit/apply/assemble and
leaves the expensive clean/transcribe stages cached.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import apply as apply_mod
from . import assemble as assemble_mod
from . import audit as audit_mod
from . import plan as plan_mod
from . import probe as probe_mod
from . import receipts as receipts_mod
from . import transcribe as transcribe_mod
from . import voice_chain as voice_chain_mod
from .config import AppConfig
from .ffmpeg import measure_loudness
from .pauses import build_pause_plan

STAGE_ORDER = ["probe", "clean", "plan-pauses", "transcribe", "plan-fillers", "audit", "apply"]
ALL_STAGES = STAGE_ORDER + ["assemble"]

# Bump a stage's version to force every run to treat existing cache entries
# for that stage as stale, even though (source sha256, profile sha256) is
# unchanged (e.g. after fixing a bug in that stage's logic).
STAGE_VERSIONS: dict[str, int] = {
    "probe": 1,
    "clean": 1,
    # v2: silence threshold is relative to integrated loudness (pauses.noise
    # "0LU"); v1 plans made on cleaned audio with the absolute -35dB found nothing.
    "plan-pauses": 2,
    "transcribe": 1,
    "plan-fillers": 1,
    "audit": 1,
    "apply": 1,
    "assemble": 1,
}


class RunError(RuntimeError):
    pass


@dataclass
class StageOutcome:
    name: str
    status: str  # "ran" | "cached" | "skipped" | "planned"
    elapsed_s: float = 0.0
    detail: dict = field(default_factory=dict)


@dataclass
class PartReport:
    stem: str
    source: Path
    part_dir: Path
    clean_wav: Path | None = None
    edited_wav: Path | None = None
    plan_path: Path | None = None
    transcript_path: Path | None = None
    probe_before: dict | None = None
    loudness_after_clean: dict | None = None
    stages: list[StageOutcome] = field(default_factory=list)
    seconds_removed: float = 0.0
    disabled_filler_proposals: list[dict] = field(default_factory=list)


@dataclass
class RunReport:
    episode_yaml: Path
    profile: str
    profile_config_path: Path | None
    episode_root: Path
    model_size: str = "small"
    out_dir: Path = Path("out")
    skip: list[str] = field(default_factory=list)
    parts: list[PartReport] = field(default_factory=list)
    assemble_stage: StageOutcome | None = None
    assemble_result: dict | None = None
    dry_run: bool = False


def _hash_files(*paths: Path) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(audit_mod.sha256_of_file(Path(p)).encode("utf-8"))
    return h.hexdigest()


def _profile_sha256(config_path: Path | None) -> str:
    if config_path is not None and Path(config_path).is_file():
        return hashlib.sha256(Path(config_path).read_bytes()).hexdigest()
    return hashlib.sha256(b"podcast-autopilot-default-profile").hexdigest()


def _load_cache(cache_path: Path) -> dict:
    if not cache_path.is_file():
        return {}
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache_path: Path, cache: dict) -> None:
    cache_path.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def _cache_hit(cache: dict, stage: str, cache_key: str, profile_sha: str, outputs: list[Path]) -> bool:
    record = cache.get(stage)
    if not record:
        return False
    if (
        record.get("cache_key") != cache_key
        or record.get("profile_sha256") != profile_sha
        or record.get("version") != STAGE_VERSIONS[stage]
    ):
        return False
    return all(Path(p).is_file() for p in outputs)


def _record(cache: dict, stage: str, cache_key: str, profile_sha: str, extra: dict | None = None) -> None:
    cache[stage] = {
        "cache_key": cache_key,
        "profile_sha256": profile_sha,
        "version": STAGE_VERSIONS[stage],
        **(extra or {}),
    }


def _transcribe_cache_key(clean_wav: Path, model_size: str) -> str:
    return hashlib.sha256(f"{_hash_files(clean_wav)}|model={model_size}".encode("utf-8")).hexdigest()


def _loudness_after_clean(clean_receipt: Path, clean_wav: Path, config: AppConfig, measure: bool) -> dict | None:
    """Post-clean loudness in probe format ({input_i, input_tp}); the clean
    receipt already holds the verification pass, so fall back to a fresh
    measurement only when the receipt is unavailable (e.g. --skip clean)."""
    if clean_receipt.is_file():
        try:
            verification = json.loads(clean_receipt.read_text(encoding="utf-8")).get("verification") or {}
            lufs, tp = verification.get("lufs"), verification.get("true_peak_dbtp")
            if lufs is not None and tp is not None:
                return {"input_i": float(lufs), "input_tp": float(tp), "source": "clean_receipt"}
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            pass
    if measure and clean_wav.is_file():
        measured = measure_loudness(clean_wav, config)
        return {
            "input_i": float(measured.get("input_i", "nan")),
            "input_tp": float(measured.get("input_tp", "nan")),
            "source": "measured",
        }
    return None


def run_part(
    source: Path,
    parts_dir: Path,
    config: AppConfig,
    profile_sha: str,
    model_size: str,
    skip: set[str],
    force: bool,
    dry_run: bool,
) -> PartReport:
    source = Path(source)
    part_dir = Path(parts_dir) / source.stem
    part_dir.mkdir(parents=True, exist_ok=True)
    cache_path = part_dir / "stage_cache.json"
    cache = {} if force else _load_cache(cache_path)

    report = PartReport(stem=source.stem, source=source, part_dir=part_dir)

    if not source.is_file():
        raise RunError(f"part not found: {source}")

    # --- probe ---
    stage = "probe"
    source_sha = audit_mod.sha256_of_file(source)
    if _cache_hit(cache, stage, source_sha, profile_sha, []) and isinstance(cache[stage].get("probe"), dict):
        report.probe_before = cache[stage]["probe"]
        report.stages.append(StageOutcome(stage, "cached"))
    elif dry_run:
        report.stages.append(StageOutcome(stage, "planned"))
    else:
        t0 = time.monotonic()
        report.probe_before = probe_mod.probe_audio(source, config)
        _record(cache, stage, source_sha, profile_sha, {"probe": report.probe_before})
        _save_cache(cache_path, cache)
        report.stages.append(StageOutcome(stage, "ran", time.monotonic() - t0))

    # --- clean ---
    stage = "clean"
    clean_wav = part_dir / f"{source.stem}.clean.wav"
    clean_receipt = part_dir / "clean_receipt.json"
    report.clean_wav = clean_wav
    if stage in skip:
        if not clean_wav.is_file():
            raise RunError(f"--skip clean requested but {clean_wav} does not exist yet")
        report.stages.append(StageOutcome(stage, "skipped"))
    else:
        key = source_sha
        if dry_run:
            status = "cached" if _cache_hit(cache, stage, key, profile_sha, [clean_wav, clean_receipt]) else "planned"
            report.stages.append(StageOutcome(stage, status))
        elif _cache_hit(cache, stage, key, profile_sha, [clean_wav, clean_receipt]):
            report.stages.append(StageOutcome(stage, "cached"))
        else:
            t0 = time.monotonic()
            out_wav, out_receipt = voice_chain_mod.clean_audio(source, parts_dir, config)
            if out_receipt != clean_receipt:
                shutil.move(str(out_receipt), str(clean_receipt))
            _record(cache, stage, key, profile_sha)
            _save_cache(cache_path, cache)
            report.stages.append(StageOutcome(stage, "ran", time.monotonic() - t0))

    report.loudness_after_clean = _loudness_after_clean(clean_receipt, clean_wav, config, measure=not dry_run)

    if dry_run and not clean_wav.is_file():
        # Nothing downstream can be previewed without the cleaned audio.
        for name in ("plan-pauses", "transcribe", "plan-fillers", "audit", "apply"):
            report.stages.append(StageOutcome(name, "planned"))
        return report

    # --- plan-pauses ---
    stage = "plan-pauses"
    plan_path = part_dir / "plan.json"
    report.plan_path = plan_path
    pauses_reran = False
    if stage in skip:
        if not plan_path.is_file():
            raise RunError(f"--skip plan-pauses requested but {plan_path} does not exist yet")
        report.stages.append(StageOutcome(stage, "skipped"))
    else:
        key = _hash_files(clean_wav) if clean_wav.is_file() else "missing"
        if dry_run:
            status = "cached" if clean_wav.is_file() and _cache_hit(cache, stage, key, profile_sha, [plan_path]) else "planned"
            report.stages.append(StageOutcome(stage, status))
        elif _cache_hit(cache, stage, key, profile_sha, [plan_path]):
            report.stages.append(StageOutcome(stage, "cached"))
        else:
            t0 = time.monotonic()
            pause_plan = build_pause_plan(clean_wav, config)
            plan_mod.save_plan(pause_plan, plan_path)
            _record(cache, stage, key, profile_sha)
            _save_cache(cache_path, cache)
            report.stages.append(StageOutcome(stage, "ran", time.monotonic() - t0))
            pauses_reran = True

    # --- transcribe ---
    stage = "transcribe"
    transcript_path = part_dir / "transcript.json"
    report.transcript_path = transcript_path
    if stage in skip:
        if not transcript_path.is_file():
            raise RunError(f"--skip transcribe requested but {transcript_path} does not exist yet")
        report.stages.append(StageOutcome(stage, "skipped"))
    else:
        # The transcript depends on the model as much as on the audio, so
        # `--model medium` after a `--model small` run must not reuse it.
        key = _transcribe_cache_key(clean_wav, model_size) if clean_wav.is_file() else "missing"
        if dry_run:
            status = "cached" if clean_wav.is_file() and _cache_hit(cache, stage, key, profile_sha, [transcript_path]) else "planned"
            report.stages.append(StageOutcome(stage, status))
        elif _cache_hit(cache, stage, key, profile_sha, [transcript_path]):
            report.stages.append(StageOutcome(stage, "cached"))
        else:
            t0 = time.monotonic()
            data = transcribe_mod.transcribe_audio(clean_wav, model_size=model_size, config=config)
            transcribe_mod.save_transcript(data, transcript_path)
            transcribe_mod.write_srt(data["segments"], part_dir / "transcript.srt")
            transcribe_mod.write_markdown(data["segments"], part_dir / "transcript.md")
            _record(cache, stage, key, profile_sha, {"language": data.get("language"), "model_size": model_size})
            _save_cache(cache_path, cache)
            report.stages.append(StageOutcome(stage, "ran", time.monotonic() - t0))

    # --- plan-fillers ---
    stage = "plan-fillers"
    if stage in skip:
        report.stages.append(StageOutcome(stage, "skipped"))
    else:
        key = _hash_files(clean_wav, transcript_path) if clean_wav.is_file() and transcript_path.is_file() else "missing"
        # plan-fillers merges into plan.json, so its key cannot include that
        # file; instead it must rerun whenever plan-pauses just rewrote it
        # (a fresh pause-only plan holds none of the earlier proposals).
        if dry_run:
            status = "cached" if clean_wav.is_file() and transcript_path.is_file() and _cache_hit(cache, stage, key, profile_sha, [plan_path]) else "planned"
            report.stages.append(StageOutcome(stage, status))
        elif not pauses_reran and _cache_hit(cache, stage, key, profile_sha, [plan_path]):
            report.stages.append(StageOutcome(stage, "cached"))
        else:
            t0 = time.monotonic()
            transcript_data = transcribe_mod.load_transcript(transcript_path)
            words = transcribe_mod.words_from_transcript(transcript_data)
            candidates = transcribe_mod.detect_fillers(
                words,
                filler_words=config.filler_words,
                pause_threshold_s=config.filler_pause_threshold_s,
                min_probability=config.filler_min_probability,
            )
            edit_plan = plan_mod.load_plan(plan_path)
            edit_plan.items = transcribe_mod.merge_filler_items(edit_plan.items, candidates)
            result = audit_mod.audit_plan(edit_plan, clean_wav)
            if not result.ok:
                raise RunError(f"plan-fillers produced an invalid plan for {source}: {'; '.join(result.errors)}")
            plan_mod.save_plan(edit_plan, plan_path)
            _record(cache, stage, key, profile_sha, {"candidates": len(candidates)})
            _save_cache(cache_path, cache)
            report.stages.append(StageOutcome(stage, "ran", time.monotonic() - t0))

    # --- audit ---
    stage = "audit"
    key = _hash_files(plan_path, clean_wav)
    if dry_run:
        status = "cached" if _cache_hit(cache, stage, key, profile_sha, []) else "planned"
        report.stages.append(StageOutcome(stage, status))
    elif _cache_hit(cache, stage, key, profile_sha, []):
        cached_extra = cache[stage]
        report.seconds_removed = cached_extra["seconds_removed"]
        report.disabled_filler_proposals = cached_extra["disabled_filler_proposals"]
        report.stages.append(StageOutcome(stage, "cached"))
    else:
        t0 = time.monotonic()
        loaded_plan = plan_mod.load_plan(plan_path)
        audit_result = audit_mod.audit_plan(loaded_plan, clean_wav)
        if not audit_result.ok:
            raise RunError(f"audit failed for {source}: {'; '.join(audit_result.errors)}")
        report.seconds_removed = audit_result.total_cut_duration
        report.disabled_filler_proposals = [
            {"id": it.id, "start": it.start, "end": it.end, "reason": it.reason}
            for it in loaded_plan.items
            if it.kind == "filler" and not it.enabled
        ]
        _record(cache, stage, key, profile_sha, {
            "seconds_removed": report.seconds_removed,
            "disabled_filler_proposals": report.disabled_filler_proposals,
        })
        _save_cache(cache_path, cache)
        report.stages.append(StageOutcome(stage, "ran", time.monotonic() - t0))

    # --- apply ---
    stage = "apply"
    edited_wav = part_dir / f"{source.stem}.edited.wav"
    receipt_path = part_dir / "receipt.json"
    report.edited_wav = edited_wav
    if stage in skip:
        if not edited_wav.is_file():
            raise RunError(f"--skip apply requested but {edited_wav} does not exist yet")
        report.stages.append(StageOutcome(stage, "skipped"))
    else:
        key = _hash_files(plan_path, clean_wav)
        if dry_run:
            status = "cached" if _cache_hit(cache, stage, key, profile_sha, [edited_wav, receipt_path]) else "planned"
            report.stages.append(StageOutcome(stage, status))
        elif _cache_hit(cache, stage, key, profile_sha, [edited_wav, receipt_path]):
            report.stages.append(StageOutcome(stage, "cached"))
        else:
            t0 = time.monotonic()
            loaded_plan = plan_mod.load_plan(plan_path)
            nested_output = apply_mod.apply_plan(loaded_plan, clean_wav, part_dir, config)
            if nested_output != edited_wav:
                shutil.move(str(nested_output), str(edited_wav))
                shutil.rmtree(nested_output.parent, ignore_errors=True)
            receipts_mod.write_receipt(loaded_plan, clean_wav, plan_path, edited_wav, part_dir, config)
            _record(cache, stage, key, profile_sha)
            _save_cache(cache_path, cache)
            report.stages.append(StageOutcome(stage, "ran", time.monotonic() - t0))

    return report


def _assemble_manifest_for(manifest: assemble_mod.EpisodeManifest, edited_parts: list[Path]) -> assemble_mod.EpisodeManifest:
    # assemble resolves relative part paths against the manifest's directory
    # (examples/ for the bundled manifest), but the edited parts live under
    # --out-dir, which is relative to the *current* directory by default
    # ("out"). Hand over absolute paths so both conventions cannot collide.
    return manifest.model_copy(update={"parts": [str(Path(p).resolve()) for p in edited_parts]})


def run_episode(
    episode_yaml: Path,
    config: AppConfig,
    profile_name: str,
    profile_config_path: Path | None,
    model_size: str,
    out_dir: Path = Path("out"),
    skip: list[str] | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> RunReport:
    episode_yaml = Path(episode_yaml)
    if not episode_yaml.is_file():
        raise RunError(f"episode manifest not found: {episode_yaml}")

    skip_set = set(skip or [])
    unknown = skip_set - set(ALL_STAGES)
    if unknown:
        raise RunError(f"unknown --skip stage(s): {sorted(unknown)}; valid stages are {ALL_STAGES}")

    manifest = assemble_mod.load_manifest(episode_yaml)
    base_dir = episode_yaml.resolve().parent
    profile_sha = _profile_sha256(profile_config_path)

    episode_root = Path(out_dir) / episode_yaml.stem
    parts_dir = episode_root / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)

    report = RunReport(
        episode_yaml=episode_yaml,
        profile=profile_name,
        profile_config_path=profile_config_path,
        episode_root=episode_root,
        model_size=model_size,
        out_dir=Path(out_dir),
        skip=sorted(skip_set),
        dry_run=dry_run,
    )

    edited_parts: list[Path] = []
    for part in manifest.parts:
        source = assemble_mod._resolve(part, base_dir)
        part_report = run_part(source, parts_dir, config, profile_sha, model_size, skip_set, force, dry_run)
        report.parts.append(part_report)
        edited_parts.append(part_report.edited_wav or source)

    if "assemble" in skip_set:
        report.assemble_stage = StageOutcome("assemble", "skipped")
        return report

    all_edited_ready = all(p.is_file() for p in edited_parts)
    if dry_run:
        status = "planned"
        if all_edited_ready:
            run_manifest = _assemble_manifest_for(manifest, edited_parts)
            key = _hash_files(episode_yaml, *edited_parts)
            episode_cache_path = episode_root / "assemble_cache.json"
            episode_cache = _load_cache(episode_cache_path)
            if _cache_hit(episode_cache, "assemble", key, profile_sha, []):
                status = "cached"
        report.assemble_stage = StageOutcome("assemble", status)
        return report

    if not all_edited_ready:
        raise RunError("cannot assemble: not every part finished 'apply' (see --dry-run for a preview)")

    run_manifest = _assemble_manifest_for(manifest, edited_parts)
    key = _hash_files(episode_yaml, *edited_parts)
    episode_cache_path = episode_root / "assemble_cache.json"
    episode_cache = {} if force else _load_cache(episode_cache_path)
    stem = f"ep{manifest.episode:02d}"
    expected_mp3 = episode_root / stem / f"{stem}.mp3"
    expected_receipt = episode_root / stem / "receipt.json"

    t0 = time.monotonic()
    if _cache_hit(episode_cache, "assemble", key, profile_sha, [expected_mp3, expected_receipt]):
        report.assemble_stage = StageOutcome("assemble", "cached")
        with open(expected_receipt, encoding="utf-8") as fh:
            receipt = json.load(fh)
        report.assemble_result = {
            "output": expected_mp3,
            "receipt": expected_receipt,
            "duration": receipt["duration"],
            "loudness": receipt["loudness"],
        }
    else:
        result = assemble_mod.assemble_from_manifest(
            run_manifest, base_dir, episode_root, config,
            manifest_record={"path": str(episode_yaml), "sha256": audit_mod.sha256_of_file(episode_yaml)},
        )
        _record(episode_cache, "assemble", key, profile_sha)
        _save_cache(episode_cache_path, episode_cache)
        report.assemble_stage = StageOutcome("assemble", "ran", time.monotonic() - t0)
        report.assemble_result = result

    return report


def reapply_command(report: RunReport) -> str:
    """A copy-pasteable command that re-renders after a human edits a part's plan.json.

    Caching means this is exactly the original command: unchanged stages
    (clean/plan-pauses/transcribe/plan-fillers) are skipped automatically,
    only audit/apply/assemble re-run for the parts whose plan.json changed.
    """
    parts = [
        f'python -m podcast_autopilot run "{report.episode_yaml}"',
        f"--profile {report.profile}",
        f"--model {report.model_size}",
        f'--out-dir "{report.out_dir}"',
    ]
    if report.profile_config_path is not None:
        # Pin the exact profile file the run used, so the re-apply cannot
        # silently resolve to a different profiles/*.yaml.
        parts.append(f'--config "{report.profile_config_path}"')
    for stage in report.skip:
        parts.append(f"--skip {stage}")
    return " ".join(parts)


def _fmt_loudness(info: dict | None) -> str:
    if not info:
        return "n/a"
    lufs = info.get("input_i")
    tp = info.get("input_tp")
    if lufs is None or tp is None:
        return "n/a"
    return f"{lufs:.1f} LUFS / {tp:.1f} dBTP"


def write_run_report(report: RunReport, path: Path) -> Path:
    lines: list[str] = []
    lines.append(f"# Run Report: {report.episode_yaml.stem}")
    lines.append("")
    lines.append(f"- Generated: {datetime_now_iso()}")
    lines.append(f"- Episode manifest: `{report.episode_yaml}`")
    profile_desc = str(report.profile_config_path) if report.profile_config_path else "built-in defaults"
    lines.append(f"- Profile: `{report.profile}` ({profile_desc})")
    if report.dry_run:
        lines.append("- Mode: **dry run** (no stages were executed; statuses below are a preview)")
    lines.append("")

    for part in report.parts:
        lines.append(f"## Part: {part.stem}")
        lines.append("")
        lines.append(f"- Source: `{part.source}`")
        lines.append(f"- Loudness before clean: {_fmt_loudness(part.probe_before)}")
        lines.append(f"- Loudness after clean: {_fmt_loudness(part.loudness_after_clean)}")
        lines.append(f"- Seconds removed (pauses + enabled fillers): {part.seconds_removed:.2f}s")
        if part.transcript_path:
            lines.append(f"- Transcript: `{part.transcript_path}`")
        if part.plan_path:
            lines.append(f"- Edit plan: `{part.plan_path}`")
        lines.append("")
        lines.append("| Stage | Status | Time (s) |")
        lines.append("|---|---|---|")
        for stage in part.stages:
            time_str = f"{stage.elapsed_s:.2f}" if stage.status == "ran" else "-"
            lines.append(f"| {stage.name} | {stage.status} | {time_str} |")
        lines.append("")

        if part.disabled_filler_proposals:
            lines.append(f"### Disabled filler proposals for human review ({len(part.disabled_filler_proposals)})")
            lines.append("")
            lines.append("| id | start (s) | end (s) | reason |")
            lines.append("|---|---|---|---|")
            for item in part.disabled_filler_proposals:
                lines.append(f"| {item['id']} | {item['start']:.2f} | {item['end']:.2f} | {item['reason']} |")
            lines.append("")

    lines.append("## Assembly")
    lines.append("")
    if report.assemble_stage:
        time_str = f"{report.assemble_stage.elapsed_s:.2f}s" if report.assemble_stage.status == "ran" else report.assemble_stage.status
        lines.append(f"- Status: {report.assemble_stage.status} ({time_str})")
    if report.assemble_result:
        lines.append(f"- Output: `{report.assemble_result['output']}`")
        lines.append(f"- Receipt: `{report.assemble_result['receipt']}`")
        lines.append(f"- Duration: {report.assemble_result['duration']:.1f}s")
        lines.append(f"- Loudness (final MP3): {_fmt_loudness(report.assemble_result['loudness'])}")
    lines.append("")

    lines.append("## Re-apply after editing plan.json")
    lines.append("")
    lines.append(
        "Enable/disable items in a part's `plan.json` (by hand, or via the Streamlit app's "
        "checkboxes), then re-run the same command below. Caching skips every stage whose "
        "input did not change, so this only re-runs `audit` / `apply` for the edited part(s) "
        "and then `assemble`:"
    )
    lines.append("")
    lines.append("```")
    lines.append(reapply_command(report))
    lines.append("```")
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def datetime_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
