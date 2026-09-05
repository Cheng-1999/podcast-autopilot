"""Episode discovery and status, derived from manifests under episodes/ and
examples/ plus whatever the pipeline already left behind under out/<id>/
(stage_cache.json per part, RUN_REPORT.md, receipt.json) -- nothing here is a
new source of truth, it only reads what run.py already writes."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .. import assemble as assemble_mod

STATUS_NEVER_RUN = "never-run"
STATUS_RUNNING = "running"
STATUS_NEEDS_REVIEW = "needs-review"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_INVALID = "invalid"


@dataclass
class ManifestRef:
    id: str
    path: Path
    example: bool


def discover_manifests(project_root: Path) -> list[ManifestRef]:
    """episodes/*.yaml (real, gitignored) and examples/*.yaml (bundled
    fixtures); an id present in both is served from episodes/."""
    refs: dict[str, ManifestRef] = {}
    for dir_name, example in (("examples", True), ("episodes", False)):
        directory = project_root / dir_name
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.yaml")):
            refs[path.stem] = ManifestRef(id=path.stem, path=path, example=example)
    return sorted(refs.values(), key=lambda r: r.id)


def find_manifest(project_root: Path, episode_id: str) -> Optional[ManifestRef]:
    for ref in discover_manifests(project_root):
        if ref.id == episode_id:
            return ref
    return None


def load_manifest_safe(path: Path):
    try:
        return assemble_mod.load_manifest(path), None
    except Exception as exc:  # noqa: BLE001 - surfaced to the client as `error`
        return None, str(exc)


def part_stems(manifest: assemble_mod.EpisodeManifest, base_dir: Path) -> list[str]:
    return [assemble_mod._resolve(p, base_dir).stem for p in manifest.parts]


def episode_paths(project_root: Path, episode_id: str, out_dir_name: str = "out") -> tuple[Path, Path, Path]:
    episode_root = project_root / out_dir_name / episode_id
    return episode_root, episode_root / "RUN_REPORT.md", episode_root / "parts"


# --- RUN_REPORT.md parsing -------------------------------------------------

_PART_HEADER = re.compile(r"^## Part: (.+)$")
_FLOAT_RE = re.compile(r"(-?\d+\.?\d*)")


def _is_float(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


def _unbacktick(value: str) -> str:
    return value.strip().strip("`")


def _parse_trailing_float(line: str) -> Optional[float]:
    matches = _FLOAT_RE.findall(line)
    return float(matches[-1]) if matches else None


def _extract_reapply_command(text: str) -> Optional[str]:
    idx = text.find("## Re-apply")
    if idx == -1:
        return None
    fence_start = text.find("```", idx)
    if fence_start == -1:
        return None
    fence_end = text.find("```", fence_start + 3)
    if fence_end == -1:
        return None
    return text[fence_start + 3:fence_end].strip()


def parse_run_report(text: str) -> dict:
    result: dict = {
        "dry_run": "**dry run**" in text,
        "parts": [],
        "assembly": {},
        "reapply_command": _extract_reapply_command(text),
    }
    current_part: Optional[dict] = None
    table_mode: Optional[str] = None  # None | "stages" | "fillers" | "assembly"

    for raw_line in text.splitlines():
        line = raw_line
        stripped = line.strip()

        part_match = _PART_HEADER.match(line)
        if part_match:
            current_part = {
                "stem": part_match.group(1),
                "source": None,
                "loudness_before": None,
                "loudness_after": None,
                "seconds_removed": None,
                "transcript": None,
                "plan": None,
                "stages": [],
                "disabled_filler_proposals": [],
            }
            result["parts"].append(current_part)
            table_mode = None
            continue
        if line.startswith("## Assembly"):
            current_part = None
            table_mode = "assembly"
            continue
        if line.startswith("## Re-apply"):
            current_part = None
            table_mode = None
            continue

        if not stripped:
            if table_mode in ("stages", "fillers"):
                table_mode = None
            continue

        if current_part is not None:
            if line.startswith("- Source: "):
                current_part["source"] = _unbacktick(line.split(": ", 1)[1])
            elif line.startswith("- Loudness before clean: "):
                current_part["loudness_before"] = line.split(": ", 1)[1].strip()
            elif line.startswith("- Loudness after clean: "):
                current_part["loudness_after"] = line.split(": ", 1)[1].strip()
            elif line.startswith("- Seconds removed"):
                current_part["seconds_removed"] = _parse_trailing_float(line)
            elif line.startswith("- Transcript: "):
                current_part["transcript"] = _unbacktick(line.split(": ", 1)[1])
            elif line.startswith("- Edit plan: "):
                current_part["plan"] = _unbacktick(line.split(": ", 1)[1])
            elif line.startswith("| Stage | Status"):
                table_mode = "stages"
            elif line.startswith("### Disabled filler proposals"):
                table_mode = None
            elif line.startswith("| id | start"):
                table_mode = "fillers"
            elif line.startswith("|"):
                inner = stripped.strip("|")
                if set(inner.replace("|", "").strip()) == {"-"}:
                    continue  # markdown table separator row
                cells = [c.strip() for c in inner.split("|")]
                if table_mode == "stages" and len(cells) == 3:
                    name, status, time_s = cells
                    current_part["stages"].append({
                        "name": name, "status": status,
                        "elapsed": float(time_s) if _is_float(time_s) else None,
                    })
                elif table_mode == "fillers" and len(cells) == 4:
                    fid, start, end, reason = cells
                    if _is_float(start) and _is_float(end):
                        current_part["disabled_filler_proposals"].append(
                            {"id": fid, "start": float(start), "end": float(end), "reason": reason}
                        )
        elif table_mode == "assembly":
            if line.startswith("- Status: "):
                result["assembly"]["status"] = line.split(": ", 1)[1].strip()
            elif line.startswith("- Output: "):
                result["assembly"]["output"] = _unbacktick(line.split(": ", 1)[1])
            elif line.startswith("- Receipt: "):
                result["assembly"]["receipt"] = _unbacktick(line.split(": ", 1)[1])
            elif line.startswith("- Duration: "):
                result["assembly"]["duration"] = _parse_trailing_float(line)
            elif line.startswith("- Loudness (final MP3): "):
                result["assembly"]["loudness"] = line.split(": ", 1)[1].strip()

    return result


# --- status derivation -------------------------------------------------------


def compute_status(
    project_root: Path,
    episode_id: str,
    manifest: Optional[assemble_mod.EpisodeManifest],
    job_manager=None,
    out_dir_name: str = "out",
) -> dict:
    active_job = job_manager.active_job_for_episode(episode_id) if job_manager is not None else None
    episode_root, report_path, parts_dir = episode_paths(project_root, episode_id, out_dir_name)

    if active_job is not None:
        status = STATUS_RUNNING
    elif not episode_root.exists():
        status = STATUS_NEVER_RUN
    elif report_path.is_file():
        parsed = parse_run_report(report_path.read_text(encoding="utf-8"))
        needs_review = any(p["disabled_filler_proposals"] for p in parsed["parts"])
        status = STATUS_NEEDS_REVIEW if needs_review else STATUS_DONE
    else:
        has_stage_cache = parts_dir.is_dir() and any(parts_dir.glob("*/stage_cache.json"))
        status = STATUS_FAILED if has_stage_cache else STATUS_NEVER_RUN

    last_run_time = report_path.stat().st_mtime if report_path.is_file() else None

    final_mp3 = duration = lufs = None
    if manifest is not None:
        ep_stem = f"ep{manifest.episode:02d}"
        receipt_path = episode_root / ep_stem / "receipt.json"
        if receipt_path.is_file():
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                final_mp3 = (receipt.get("output") or {}).get("path")
                duration = receipt.get("duration")
                lufs = (receipt.get("loudness") or {}).get("input_i")
            except (json.JSONDecodeError, OSError):
                pass

    return {
        "status": status,
        "last_run_time": last_run_time,
        "final_mp3": final_mp3,
        "duration": duration,
        "lufs": lufs,
        "job_id": active_job.id if active_job else None,
    }


def episode_summary(project_root: Path, ref: ManifestRef, job_manager=None) -> dict:
    manifest, error = load_manifest_safe(ref.path)
    base = {
        "id": ref.id,
        "path": str(ref.path.relative_to(project_root)),
        "example": ref.example,
        "title": None,
        "episode": None,
        "parts": [],
        "error": error,
    }
    if manifest is None:
        base["status"] = STATUS_INVALID
        return base
    base["title"] = manifest.title
    base["episode"] = manifest.episode
    base["parts"] = manifest.parts
    base.update(compute_status(project_root, ref.id, manifest, job_manager))
    return base


def episode_detail(project_root: Path, ref: ManifestRef, job_manager=None) -> dict:
    detail = episode_summary(project_root, ref, job_manager)
    _episode_root, report_path, _parts_dir = episode_paths(project_root, ref.id)
    detail["report_available"] = report_path.is_file()
    if report_path.is_file():
        parsed = parse_run_report(report_path.read_text(encoding="utf-8"))
        detail["parts_detail"] = parsed["parts"]
        detail["assembly"] = parsed["assembly"]
        detail["reapply_command"] = parsed["reapply_command"]
    else:
        detail["parts_detail"] = []
        detail["assembly"] = {}
        detail["reapply_command"] = None
    return detail
