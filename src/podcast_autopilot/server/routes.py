"""All /api routes. Every handler wraps existing pipeline modules (plan,
audit, transcribe, run) instead of re-implementing their logic; the server's
job is orchestration (background jobs, progress, media serving), not
business logic."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .. import audit as audit_mod
from .. import cli as cli_mod
from .. import plan as plan_mod
from .. import run as run_mod
from ..config import DEFAULT_MODELS_DIR, FFmpegNotFoundError, load_config, resolve_ffmpeg_binaries
from . import episodes as episodes_mod
from . import media as media_mod
from .jobs import Job, JobManager

router = APIRouter(prefix="/api")


def _job_manager(request: Request) -> JobManager:
    return request.app.state.job_manager


def _project_root(request: Request) -> Path:
    return request.app.state.project_root


def _ref_or_404(project_root: Path, episode_id: str) -> episodes_mod.ManifestRef:
    ref = episodes_mod.find_manifest(project_root, episode_id)
    if ref is None:
        raise HTTPException(404, f"episode not found: {episode_id}")
    return ref


def _part_dir_or_404(project_root: Path, episode_id: str, ref: episodes_mod.ManifestRef, part_id: str) -> Path:
    manifest, error = episodes_mod.load_manifest_safe(ref.path)
    if manifest is None:
        raise HTTPException(422, f"manifest invalid: {error}")
    base_dir = ref.path.resolve().parent
    if part_id not in episodes_mod.part_stems(manifest, base_dir):
        raise HTTPException(404, f"part not found: {part_id}")
    _episode_root, _report_path, parts_dir = episodes_mod.episode_paths(project_root, episode_id)
    return parts_dir / part_id


# --- health ------------------------------------------------------------------


@router.get("/health")
def health() -> dict:
    config = load_config(None)
    try:
        ffmpeg, ffprobe = resolve_ffmpeg_binaries(config)
        ffmpeg_ok = True
    except FFmpegNotFoundError:
        ffmpeg = ffprobe = None
        ffmpeg_ok = False

    whisper_models = {}
    for size in ("small", "medium"):
        snapshots = DEFAULT_MODELS_DIR / f"models--Systran--faster-whisper-{size}" / "snapshots"
        whisper_models[size] = snapshots.is_dir() and any(snapshots.iterdir())

    try:
        free_disk_gb = round(shutil.disk_usage(DEFAULT_MODELS_DIR.parent.parent).free / (1024 ** 3), 1)
    except OSError:
        free_disk_gb = None

    return {
        "ffmpeg": str(ffmpeg) if ffmpeg else None,
        "ffprobe": str(ffprobe) if ffprobe else None,
        "ffmpeg_ok": ffmpeg_ok,
        "whisper_models": whisper_models,
        "free_disk_gb": free_disk_gb,
    }


# --- episodes ------------------------------------------------------------------


@router.get("/episodes")
def list_episodes(request: Request) -> list[dict]:
    project_root = _project_root(request)
    job_manager = _job_manager(request)
    refs = episodes_mod.discover_manifests(project_root)
    return [episodes_mod.episode_summary(project_root, ref, job_manager) for ref in refs]


@router.get("/episodes/{episode_id}")
def get_episode(episode_id: str, request: Request) -> dict:
    project_root = _project_root(request)
    ref = _ref_or_404(project_root, episode_id)
    return episodes_mod.episode_detail(project_root, ref, _job_manager(request))


@router.get("/episodes/{episode_id}/report", response_class=PlainTextResponse)
def get_report(episode_id: str, request: Request) -> str:
    project_root = _project_root(request)
    _ref_or_404(project_root, episode_id)
    _root, report_path, _parts = episodes_mod.episode_paths(project_root, episode_id)
    if not report_path.is_file():
        raise HTTPException(404, "RUN_REPORT.md not found; run the pipeline first")
    return report_path.read_text(encoding="utf-8")


class RunRequest(BaseModel):
    profile: str = "default"
    model: Optional[str] = None
    force: bool = False
    skip: list[str] = []


@router.post("/episodes/{episode_id}/run")
def run_episode(episode_id: str, body: RunRequest, request: Request) -> dict:
    project_root = _project_root(request)
    job_manager = _job_manager(request)
    ref = _ref_or_404(project_root, episode_id)

    if body.model is not None and body.model not in cli_mod.VALID_WHISPER_MODEL_SIZES:
        raise HTTPException(422, f"model must be one of {cli_mod.VALID_WHISPER_MODEL_SIZES}, got {body.model!r}")
    unknown = set(body.skip) - set(run_mod.ALL_STAGES)
    if unknown:
        raise HTTPException(422, f"unknown skip stage(s): {sorted(unknown)}; valid stages are {run_mod.ALL_STAGES}")

    profile_config_path = cli_mod._resolve_profile_config_path(body.profile)
    config = load_config(profile_config_path)
    model_size = body.model or config.whisper_model_size

    job = job_manager.submit(
        episode_id=episode_id,
        episode_yaml=ref.path,
        config=config,
        profile=body.profile,
        profile_config_path=profile_config_path,
        model=model_size,
        out_dir=project_root / "out",
        skip=body.skip,
        force=body.force,
    )
    return job.to_dict()


# --- jobs ------------------------------------------------------------------


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> dict:
    job = _job_manager(request).get(job_id)
    if job is None:
        raise HTTPException(404, f"job not found: {job_id}")
    return job.to_dict()


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request) -> dict:
    job_manager = _job_manager(request)
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(404, f"job not found: {job_id}")
    job_manager.cancel(job_id)
    return job.to_dict()


def _sse_format(evt) -> str:
    return f"id: {evt.seq}\nevent: {evt.event}\ndata: {json.dumps(evt.to_dict(), ensure_ascii=False)}\n\n"


async def _event_stream(job: Job):
    index = 0
    while True:
        events = job.events_from(index)
        if events:
            for evt in events:
                yield _sse_format(evt)
            index += len(events)
            continue
        if job.is_terminal():
            break
        await run_in_threadpool(job.wait_for_more, index, 1.0)


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request) -> StreamingResponse:
    job = _job_manager(request).get(job_id)
    if job is None:
        raise HTTPException(404, f"job not found: {job_id}")
    return StreamingResponse(_event_stream(job), media_type="text/event-stream")


# --- plan / transcript ------------------------------------------------------------------


@router.get("/episodes/{episode_id}/parts/{part_id}/plan")
def get_plan(episode_id: str, part_id: str, request: Request) -> dict:
    project_root = _project_root(request)
    ref = _ref_or_404(project_root, episode_id)
    part_dir = _part_dir_or_404(project_root, episode_id, ref, part_id)
    plan_path = part_dir / "plan.json"
    if not plan_path.is_file():
        raise HTTPException(404, "plan.json not found; run the pipeline first")
    return json.loads(plan_path.read_text(encoding="utf-8"))


class PlanItemFlag(BaseModel):
    id: str
    enabled: bool


@router.put("/episodes/{episode_id}/parts/{part_id}/plan")
def put_plan(episode_id: str, part_id: str, body: list[PlanItemFlag], request: Request):
    project_root = _project_root(request)
    ref = _ref_or_404(project_root, episode_id)
    part_dir = _part_dir_or_404(project_root, episode_id, ref, part_id)
    plan_path = part_dir / "plan.json"
    clean_wav = part_dir / f"{part_id}.clean.wav"
    if not plan_path.is_file():
        raise HTTPException(404, "plan.json not found; run the pipeline first")
    if not clean_wav.is_file():
        raise HTTPException(404, "clean audio not found; run the pipeline first")

    plan = plan_mod.load_plan(plan_path)
    flags = {item.id: item.enabled for item in body}
    for item in plan.items:
        if item.id in flags:
            item.enabled = flags[item.id]

    result = audit_mod.audit_plan(plan, clean_wav)
    if not result.ok:
        return JSONResponse(status_code=422, content={"ok": False, "errors": result.errors})

    plan_mod.save_plan(plan, plan_path)
    return {"ok": True, "seconds_removed": result.total_cut_duration, "coverage_ratio": result.coverage_ratio}


@router.get("/episodes/{episode_id}/parts/{part_id}/transcript")
def get_transcript(episode_id: str, part_id: str, request: Request) -> dict:
    project_root = _project_root(request)
    ref = _ref_or_404(project_root, episode_id)
    part_dir = _part_dir_or_404(project_root, episode_id, ref, part_id)
    transcript_path = part_dir / "transcript.json"
    if not transcript_path.is_file():
        raise HTTPException(404, "transcript.json not found; run the pipeline first")
    return json.loads(transcript_path.read_text(encoding="utf-8"))


# --- media ------------------------------------------------------------------


@router.get("/media/{episode_id}/{rel_path:path}")
def get_media(episode_id: str, rel_path: str, request: Request):
    project_root = _project_root(request)
    target = media_mod.resolve_media_path(project_root, episode_id, rel_path)
    if target is None:
        raise HTTPException(404, "file not found")

    file_size = target.stat().st_size
    content_type = media_mod.guess_content_type(target)
    byte_range = media_mod.parse_range_header(request.headers.get("range"), file_size)

    if byte_range is None:
        headers = {"Accept-Ranges": "bytes", "Content-Length": str(file_size)}
        return StreamingResponse(media_mod.iter_file_range(target, 0, file_size - 1), media_type=content_type, headers=headers)

    start, end = byte_range
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Content-Length": str(end - start + 1),
    }
    return StreamingResponse(
        media_mod.iter_file_range(target, start, end), status_code=206, media_type=content_type, headers=headers,
    )
