"""All /api routes. Every handler wraps existing pipeline modules (plan,
audit, transcribe, run) instead of re-implementing their logic; the server's
job is orchestration (background jobs, progress, media serving), not
business logic."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Optional

import numpy as np
import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import assemble as assemble_mod
from .. import audit as audit_mod
from .. import cli as cli_mod
from .. import ffmpeg as ffmpeg_mod
from .. import plan as plan_mod
from .. import probe as probe_mod
from .. import run as run_mod
from ..config import DEFAULT_MODELS_DIR, FFmpegNotFoundError, load_config, resolve_ffmpeg_binaries
from . import episodes as episodes_mod
from . import media as media_mod
from .jobs import Job, JobManager

ALLOWED_UPLOAD_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a"}

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


def _slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^\w]+", "-", text, flags=re.UNICODE)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "episode"


def _safe_segment(value: str) -> str:
    name = Path(value).name
    return name if name not in ("", ".", "..") else "_uploads"


def _validate_chapters_against_parts(manifest: assemble_mod.EpisodeManifest, base_dir: Path, config) -> None:
    if not manifest.parts:
        raise HTTPException(422, "manifest has no parts")
    total = 0.0
    for p in manifest.parts:
        part_path = assemble_mod._resolve(p, base_dir)
        if not part_path.is_file():
            raise HTTPException(422, f"part not found: {part_path}")
        try:
            total += probe_mod.probe_audio(part_path, config)["duration"]
        except Exception as exc:
            raise HTTPException(422, f"part failed to probe as audio: {part_path}: {exc}") from exc
    try:
        starts = assemble_mod._chapter_starts(manifest.chapters)
    except assemble_mod.AssembleError as exc:
        raise HTTPException(422, str(exc)) from exc
    for chapter, start in zip(manifest.chapters, starts):
        if start >= total:
            raise HTTPException(
                422,
                f"chapter {chapter.title!r} starts at {chapter.start!r} ({start:.3f}s) "
                f"but the part(s) total only {total:.3f}s",
            )


def _dump_manifest_yaml(manifest: assemble_mod.EpisodeManifest) -> str:
    return yaml.safe_dump(manifest.model_dump(mode="json", exclude_none=True), allow_unicode=True, sort_keys=False)


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


# --- uploads ------------------------------------------------------------------


@router.post("/uploads")
async def create_upload(request: Request) -> dict:
    project_root = _project_root(request)
    config = load_config(None)
    content_type = request.headers.get("content-type", "")

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is None:
            raise HTTPException(422, "missing 'file' field")
        original_name = Path(upload.filename or "").name
        if not original_name:
            raise HTTPException(422, "missing filename")
        ext = Path(original_name).suffix.lower()
        if ext not in ALLOWED_UPLOAD_EXTENSIONS:
            raise HTTPException(415, f"unsupported audio extension: {ext or '(none)'}")

        episode_segment = _safe_segment(str(form.get("episode") or "_uploads"))
        dest_dir = project_root / "media" / episode_segment
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / original_name
        dest_path.write_bytes(await upload.read())

        try:
            info = probe_mod.probe_audio(dest_path, config)
        except Exception as exc:
            dest_path.unlink(missing_ok=True)
            raise HTTPException(415, f"uploaded file failed to probe as audio: {exc}") from exc
        return {
            "path": str(dest_path.resolve()),
            "duration": info["duration"],
            "sr": info["sr"],
            "channels": info["channels"],
        }

    body = await request.json()
    path_str = body.get("path") if isinstance(body, dict) else None
    if not path_str:
        raise HTTPException(422, "missing 'path'")
    candidate = Path(path_str)
    if not candidate.is_absolute():
        raise HTTPException(422, "'path' must be an absolute path")
    if not candidate.is_file():
        raise HTTPException(404, f"file not found: {candidate}")
    try:
        info = probe_mod.probe_audio(candidate, config)
    except Exception as exc:
        raise HTTPException(415, f"file failed to probe as audio: {exc}") from exc
    return {
        "path": str(candidate.resolve()),
        "duration": info["duration"],
        "sr": info["sr"],
        "channels": info["channels"],
    }


# --- episodes ------------------------------------------------------------------


@router.get("/episodes")
def list_episodes(request: Request) -> list[dict]:
    project_root = _project_root(request)
    job_manager = _job_manager(request)
    refs = episodes_mod.discover_manifests(project_root)
    return [episodes_mod.episode_summary(project_root, ref, job_manager) for ref in refs]


class EpisodeUpdate(BaseModel):
    chapters: list[assemble_mod.ChapterEntry] = Field(default_factory=list)
    tags: assemble_mod.TagsConfig = Field(default_factory=assemble_mod.TagsConfig)


@router.post("/episodes")
def create_episode(body: assemble_mod.EpisodeManifest, request: Request) -> dict:
    project_root = _project_root(request)
    episodes_dir = project_root / "episodes"
    slug = f"{_slugify(body.title)}-ep{body.episode:02d}"

    if episodes_mod.find_manifest(project_root, slug) is not None:
        raise HTTPException(409, f"episode already exists: {slug}")

    config = load_config(None)
    _validate_chapters_against_parts(body, episodes_dir, config)

    episodes_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = episodes_dir / f"{slug}.yaml"
    manifest_path.write_text(_dump_manifest_yaml(body), encoding="utf-8")
    return {"id": slug, "path": str(manifest_path.relative_to(project_root))}


@router.put("/episodes/{episode_id}")
def update_episode(episode_id: str, body: EpisodeUpdate, request: Request) -> dict:
    project_root = _project_root(request)
    ref = _ref_or_404(project_root, episode_id)
    if ref.example:
        raise HTTPException(400, "cannot edit a bundled example manifest")
    manifest, error = episodes_mod.load_manifest_safe(ref.path)
    if manifest is None:
        raise HTTPException(422, f"manifest invalid: {error}")

    base_dir = ref.path.resolve().parent
    config = load_config(None)
    updated = manifest.model_copy(update={"chapters": body.chapters, "tags": body.tags})
    _validate_chapters_against_parts(updated, base_dir, config)

    ref.path.write_text(_dump_manifest_yaml(updated), encoding="utf-8")
    return {"id": episode_id, "path": str(ref.path.relative_to(project_root))}


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


def _part_wav_for_peaks(ref: episodes_mod.ManifestRef, part_dir: Path, part_id: str) -> Optional[Path]:
    wav = part_dir / f"{part_id}.clean.wav"
    if wav.is_file():
        return wav
    manifest, _error = episodes_mod.load_manifest_safe(ref.path)
    if manifest is None:
        return None
    base_dir = ref.path.resolve().parent
    source = next(
        (p for p in manifest.parts if assemble_mod._resolve(p, base_dir).stem == part_id), None
    )
    if source is None:
        return None
    source_path = assemble_mod._resolve(source, base_dir)
    return source_path if source_path.is_file() else None


def _compute_peaks(pcm_bytes: bytes, buckets: int) -> list[list[int]]:
    if not pcm_bytes:
        return [[0, 0] for _ in range(buckets)]
    arr = np.frombuffer(pcm_bytes, dtype="<i2")
    if arr.size == 0:
        return [[0, 0] for _ in range(buckets)]
    peaks: list[list[int]] = []
    for chunk in np.array_split(arr, buckets):
        if chunk.size == 0:
            peaks.append([0, 0])
        else:
            peaks.append([int(chunk.min()), int(chunk.max())])
    return peaks


@router.get("/episodes/{episode_id}/parts/{part_id}/peaks")
def get_peaks(episode_id: str, part_id: str, request: Request, buckets: int = 2000) -> dict:
    if buckets <= 0:
        raise HTTPException(422, "buckets must be a positive integer")
    project_root = _project_root(request)
    ref = _ref_or_404(project_root, episode_id)
    part_dir = _part_dir_or_404(project_root, episode_id, ref, part_id)

    wav = _part_wav_for_peaks(ref, part_dir, part_id)
    if wav is None:
        raise HTTPException(404, "no audio found for part; expected clean audio or the source file")

    config = load_config(None)
    wav_sha = audit_mod.sha256_of_file(wav)
    cache_path = part_dir / f"peaks.{buckets}.json"
    if cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            cached = None
        if cached and cached.get("wav_sha256") == wav_sha and cached.get("buckets") == buckets:
            return cached

    pcm = ffmpeg_mod.decode_pcm_s16le_mono(wav, config)
    peaks = _compute_peaks(pcm, buckets)
    data = {"wav_sha256": wav_sha, "buckets": buckets, "peaks": peaks}
    part_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(data), encoding="utf-8")
    return data


# --- clips ------------------------------------------------------------------


@router.get("/episodes/{episode_id}/parts/{part_id}/clips")
def get_clips(episode_id: str, part_id: str, request: Request) -> dict:
    project_root = _project_root(request)
    ref = _ref_or_404(project_root, episode_id)
    part_dir = _part_dir_or_404(project_root, episode_id, ref, part_id)
    clips_path = part_dir / "clips.json"
    if not clips_path.is_file():
        raise HTTPException(404, "clips.json not found; run clips first")
    return json.loads(clips_path.read_text(encoding="utf-8"))


class ClipsRequest(BaseModel):
    render: bool = False


@router.post("/episodes/{episode_id}/parts/{part_id}/clips")
def post_clips(episode_id: str, part_id: str, body: ClipsRequest, request: Request) -> dict:
    project_root = _project_root(request)
    job_manager = _job_manager(request)
    ref = _ref_or_404(project_root, episode_id)
    part_dir = _part_dir_or_404(project_root, episode_id, ref, part_id)

    transcript_path = part_dir / "transcript.json"
    if not transcript_path.is_file():
        raise HTTPException(404, "transcript.json not found; run the pipeline first")

    audio_path = _part_wav_for_peaks(ref, part_dir, part_id)

    config = load_config(None)
    job = job_manager.submit_clips(
        episode_id=episode_id,
        part_id=part_id,
        part_dir=part_dir,
        config=config,
        out_dir=project_root / "out",
        render=body.render,
        audio_path=audio_path,
    )
    return job.to_dict()


# --- deliverables ------------------------------------------------------------------


@router.get("/episodes/{episode_id}/deliverables")
def get_deliverables(episode_id: str, request: Request) -> dict:
    project_root = _project_root(request)
    ref = _ref_or_404(project_root, episode_id)
    manifest, error = episodes_mod.load_manifest_safe(ref.path)
    if manifest is None:
        raise HTTPException(422, f"manifest invalid: {error}")

    episode_root, _report_path, parts_dir = episodes_mod.episode_paths(project_root, episode_id)
    stem = f"ep{manifest.episode:02d}"
    ep_dir = episode_root / stem
    base_dir = ref.path.resolve().parent

    def url(path: Path) -> Optional[str]:
        return media_mod.to_media_url(project_root, path) if path.is_file() else None

    parts_out = []
    for part_str in manifest.parts:
        part_stem = assemble_mod._resolve(part_str, base_dir).stem
        part_dir = parts_dir / part_stem
        edited = part_dir / f"{part_stem}.edited.wav"
        clips_dir = part_dir / "clips"
        clip_files = []
        if clips_dir.is_dir():
            for mp3 in sorted(clips_dir.glob("*.mp3")):
                srt = mp3.with_suffix(".srt")
                clip_files.append({"mp3": url(mp3), "srt": url(srt)})
        parts_out.append({"part": part_stem, "edited_wav": url(edited), "clips": clip_files})

    return {
        "final_mp3": url(ep_dir / f"{stem}.mp3"),
        "chapters_json": url(ep_dir / "chapters.json"),
        "receipt": url(ep_dir / "receipt.json"),
        "parts": parts_out,
    }


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
