"""Background job runner: one `run_episode` at a time, with progress events
(for SSE) and captured stdout/stderr, on top of the existing pipeline in
`run.py`. Nothing here duplicates pipeline logic -- it only wraps
`run_mod.run_episode` with a progress callback, a cancel flag, and a log file.
"""
from __future__ import annotations

import queue
import threading
import time
import uuid
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .. import assemble as assemble_mod
from .. import audit as audit_mod
from .. import clips as clips_mod
from .. import probe as probe_mod
from .. import run as run_mod
from .. import transcribe as transcribe_mod
from .. import voice_chain as voice_chain_mod
from ..config import AppConfig

TERMINAL_STATUSES = {"done", "failed", "cancelled"}

# A stage can legitimately run for a long time (e.g. `large-v3` transcription
# of a 90-minute episode on CPU), so this is deliberately generous -- it only
# exists to stop a genuinely stuck stage (a native call blocked on I/O, an
# infinite loop) from wedging the single job queue and the affected episode's
# delete/re-run forever. See jobs.py's `_run_worker` for how it is enforced.
JOB_TIMEOUT_S = 6 * 3600


class EpisodeDeletingError(RuntimeError):
    """Raised when a job is submitted for an episode that is concurrently being deleted."""

    def __init__(self, episode_id: str) -> None:
        super().__init__(f"episode {episode_id!r} is being deleted")
        self.episode_id = episode_id


class EpisodeBusyError(RuntimeError):
    """Raised when a job is submitted for an episode that already has one queued or running."""

    def __init__(self, episode_id: str) -> None:
        super().__init__(f"episode {episode_id!r} already has an active job")
        self.episode_id = episode_id


@dataclass
class JobEvent:
    seq: int
    event: str
    stage: Optional[str] = None
    part: Optional[str] = None
    elapsed: float = 0.0
    message: str = ""
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "event": self.event,
            "stage": self.stage,
            "part": self.part,
            "elapsed": self.elapsed,
            "message": self.message,
            "ts": self.ts,
        }


class _TeeWriter:
    """Writes to a log file and, line by line, into the job's event stream."""

    def __init__(self, file, job: "Job"):
        self._file = file
        self._job = job
        self._buffer = ""

    def write(self, text: str) -> int:
        self._file.write(text)
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._job.add_event("log", message=line)
        return len(text)

    def flush(self) -> None:
        self._file.flush()


class Job:
    def __init__(
        self,
        job_id: str,
        episode_id: str,
        kind: str = "run",
        episode_yaml: Optional[Path] = None,
        config: Optional[AppConfig] = None,
        profile: str = "",
        profile_config_path: Optional[Path] = None,
        model: str = "",
        out_dir: Path = Path("out"),
        skip: Optional[list[str]] = None,
        force: bool = False,
        part_id: Optional[str] = None,
        part_dir: Optional[Path] = None,
        render: bool = False,
        audio_path: Optional[Path] = None,
    ):
        self.id = job_id
        self.episode_id = episode_id
        self.kind = kind
        self.episode_yaml = episode_yaml
        self.config = config
        self.profile = profile
        self.profile_config_path = profile_config_path
        self.model = model
        self.out_dir = out_dir
        self.skip = skip or []
        self.force = force
        self.part_id = part_id
        self.part_dir = Path(part_dir) if part_dir is not None else None
        self.render = render
        self.audio_path = Path(audio_path) if audio_path is not None else None

        self.status = "queued"  # queued|running|done|failed|cancelled
        self.error: Optional[str] = None
        self.created_at = time.time()
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None
        self.cancel_requested = False
        self.log_path: Optional[Path] = None

        self._events: list[JobEvent] = []
        self._cond = threading.Condition()

    def add_event(self, event: str, stage: Optional[str] = None, part: Optional[str] = None,
                  elapsed: float = 0.0, message: str = "") -> None:
        with self._cond:
            seq = len(self._events)
            self._events.append(JobEvent(seq=seq, event=event, stage=stage, part=part, elapsed=elapsed, message=message))
            self._cond.notify_all()

    def events_from(self, index: int) -> list[JobEvent]:
        with self._cond:
            return list(self._events[index:])

    def wait_for_more(self, index: int, timeout: float = 1.0) -> bool:
        with self._cond:
            if len(self._events) > index:
                return True
            return self._cond.wait(timeout)

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def finish_if_active(self, status: str, error: Optional[str] = None,
                          event: Optional[str] = None, message: str = "") -> bool:
        """Transition to a terminal status, unless the job already reached
        one. Guards against a timed-out job's abandoned thread (see
        `JobManager._run_job_with_timeout`) finishing -- successfully or
        not -- after the watchdog already marked it failed: without this
        guard a late `done` would silently overwrite the timeout failure and
        hide that the output may have been written by an abandoned thread.
        Returns whether this call actually changed the status."""
        with self._cond:
            if self.is_terminal():
                return False
            self.status = status
            self.error = error
            self.finished_at = time.time()
            if event is not None:
                self.add_event(event, message=message)
            return True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "episode_id": self.episode_id,
            "kind": self.kind,
            "part_id": self.part_id,
            "profile": self.profile,
            "model": self.model,
            "force": self.force,
            "skip": self.skip,
            "render": self.render,
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "log_path": str(self.log_path) if self.log_path else None,
            "event_count": len(self._events),
        }


class JobManager:
    """Single background worker: jobs are processed strictly one at a time."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._lock = threading.Lock()
        self._deleting: set[str] = set()
        # Episodes whose job timed out but whose worker thread is still
        # alive in the background (Python cannot forcibly kill a thread
        # blocked in a native call). Kept "busy" until that thread actually
        # returns, so a new job or a delete cannot start while the abandoned
        # thread may still be writing the episode's output files.
        self._abandoned_episodes: set[str] = set()
        self._worker = threading.Thread(target=self._run_worker, name="dashboard-job-worker", daemon=True)
        self._worker.start()

    def submit(
        self,
        episode_id: str,
        episode_yaml: Path,
        config: AppConfig,
        profile: str,
        profile_config_path: Optional[Path],
        model: str,
        out_dir: Path,
        skip: list[str],
        force: bool,
    ) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(
            job_id, episode_id, kind="run", episode_yaml=episode_yaml, config=config, profile=profile,
            profile_config_path=profile_config_path, model=model, out_dir=out_dir, skip=skip, force=force,
        )
        with self._lock:
            if episode_id in self._deleting:
                raise EpisodeDeletingError(episode_id)
            if self._episode_busy_locked(episode_id):
                raise EpisodeBusyError(episode_id)
            self._jobs[job_id] = job
        self._queue.put(job_id)
        return job

    def submit_clips(
        self,
        episode_id: str,
        part_id: str,
        part_dir: Path,
        config: AppConfig,
        out_dir: Path,
        render: bool,
        audio_path: Optional[Path] = None,
    ) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(
            job_id, episode_id, kind="clips", config=config, out_dir=out_dir,
            part_id=part_id, part_dir=part_dir, render=render, audio_path=audio_path,
        )
        with self._lock:
            if episode_id in self._deleting:
                raise EpisodeDeletingError(episode_id)
            if self._episode_busy_locked(episode_id):
                raise EpisodeBusyError(episode_id)
            self._jobs[job_id] = job
        self._queue.put(job_id)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def _active_job_for_episode_locked(self, episode_id: str) -> Optional[Job]:
        """Caller must hold self._lock."""
        for job in self._jobs.values():
            if job.episode_id == episode_id and job.status in ("queued", "running"):
                return job
        return None

    def active_job_for_episode(self, episode_id: str) -> Optional[Job]:
        with self._lock:
            return self._active_job_for_episode_locked(episode_id)

    def _episode_busy_locked(self, episode_id: str) -> bool:
        """Caller must hold self._lock. True if a job is queued/running for
        this episode, or if a timed-out job's abandoned thread might still
        be writing its output (see `_abandoned_episodes`)."""
        if self._active_job_for_episode_locked(episode_id) is not None:
            return True
        return episode_id in self._abandoned_episodes

    def begin_delete(self, episode_id: str) -> bool:
        """Atomically check for an active (or abandoned-but-still-running)
        job and mark the episode as being deleted, so a job submitted
        concurrently with a delete cannot race it. Returns False (no state
        change) if a job is already active."""
        with self._lock:
            if self._episode_busy_locked(episode_id):
                return False
            self._deleting.add(episode_id)
            return True

    def end_delete(self, episode_id: str) -> None:
        with self._lock:
            self._deleting.discard(episode_id)

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job is None or job.is_terminal():
            return False
        job.cancel_requested = True
        return True

    def _run_worker(self) -> None:
        # This loop must never die: it is the only thing that drains the
        # queue, so an unhandled exception here (even one raised while just
        # setting a job up, before its own `run_episode` try/except) would
        # silently freeze every job for every episode submitted afterward,
        # each stuck forever as "queued". Every branch below is defensive
        # for exactly that reason.
        while True:
            job_id = self._queue.get()
            try:
                job = self.get(job_id)
                if job is None:
                    continue
                if job.cancel_requested:
                    job.status = "cancelled"
                    job.finished_at = time.time()
                    job.add_event("job_cancelled")
                    continue
                self._run_job_with_timeout(job)
            except Exception as exc:  # pragma: no cover - defensive: keep the worker alive no matter what
                job = self.get(job_id)
                if job is not None and not job.is_terminal():
                    job.status = "failed"
                    job.error = f"{type(exc).__name__}: {exc}"
                    job.finished_at = time.time()
                    job.add_event("job_failed", message=job.error)

    def _run_job_with_timeout(self, job: Job) -> None:
        """Run the job on its own thread and give up waiting after
        JOB_TIMEOUT_S so one stuck job (e.g. blocked on I/O) cannot wedge the
        queue or the episode's delete/re-run forever. If the job is still
        running when the timeout fires, `cancel_requested` is set so the
        pipeline can stop cooperatively at its next stage boundary (see
        `run._check_cancel`), but the thread cannot be forcibly killed if
        it's blocked in a native call, so it may keep running and writing to
        the episode's output files in the background. Until it actually
        returns, the episode is kept "busy" (`_abandoned_episodes`) so a new
        job or a delete cannot start and race it; `finish_if_active` on the
        Job itself stops the abandoned thread's eventual result (success or
        failure) from overwriting the timeout failure recorded here."""
        thread = threading.Thread(target=self._run_job, args=(job,), daemon=True)
        thread.start()
        thread.join(JOB_TIMEOUT_S)
        if thread.is_alive():
            job.cancel_requested = True
            # Mark the episode busy via _abandoned_episodes *before* the job
            # is exposed as terminal below, so no window exists where a
            # concurrent submit/delete can see neither an active job nor an
            # abandoned episode and race the still-running thread.
            with self._lock:
                self._abandoned_episodes.add(job.episode_id)
            timeout_msg = f"job exceeded the {JOB_TIMEOUT_S}s time limit and was abandoned"
            job.finish_if_active("failed", error=timeout_msg, event="job_failed", message=timeout_msg)
            threading.Thread(
                target=self._reap_abandoned, args=(job.episode_id, thread),
                name="dashboard-job-reaper", daemon=True,
            ).start()

    def _reap_abandoned(self, episode_id: str, thread: threading.Thread) -> None:
        """Block (on a throwaway daemon thread) until an abandoned job
        thread actually returns, then free the episode back up."""
        thread.join()
        with self._lock:
            self._abandoned_episodes.discard(episode_id)

    def _run_job(self, job: Job) -> None:
        try:
            job.status = "running"
            job.started_at = time.time()
            job.add_event("job_started")

            job.log_path = Path(job.out_dir) / job.episode_id / f"dashboard-job-{job.id}.log"
            job.log_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            job.add_event("job_failed", message=job.error)
            job.finished_at = time.time()
            return

        def on_progress(evt: dict) -> None:
            job.add_event(evt["event"], stage=evt.get("stage"), part=evt.get("part"), elapsed=evt.get("elapsed", 0.0))

        try:
            with open(job.log_path, "w", encoding="utf-8") as logf:
                tee_out, tee_err = _TeeWriter(logf, job), _TeeWriter(logf, job)
                with redirect_stdout(tee_out), redirect_stderr(tee_err):
                    if job.kind == "clips":
                        _run_clips_job(job)
                    else:
                        report = run_mod.run_episode(
                            job.episode_yaml,
                            job.config,
                            profile_name=job.profile,
                            profile_config_path=job.profile_config_path,
                            model_size=job.model,
                            out_dir=job.out_dir,
                            skip=job.skip,
                            force=job.force,
                            progress=on_progress,
                            should_cancel=lambda: job.cancel_requested,
                        )
                        run_mod.write_run_report(report, report.episode_root / "RUN_REPORT.md")
        except run_mod.CancelledError:
            job.finish_if_active("cancelled", event="job_cancelled")
        except (run_mod.RunError, assemble_mod.AssembleError, voice_chain_mod.VoiceChainError) as exc:
            job.finish_if_active("failed", error=str(exc), event="job_failed", message=str(exc))
        except Exception as exc:  # pragma: no cover - defensive: never leave a job stuck "running"
            msg = f"{type(exc).__name__}: {exc}"
            job.finish_if_active("failed", error=msg, event="job_failed", message=msg)
        else:
            job.finish_if_active("done", event="job_finished")


def _run_clips_job(job: Job) -> None:
    """Build (and optionally render) clip candidates for job.part_id, reusing
    the transcript already produced by a prior `run` job.

    Candidate generation only needs `transcript.json`; audio (clean, or the
    original source before the pipeline reaches the `clean` stage) is only
    required when `render` is requested, since that is the only step that
    actually reads samples from it.
    """
    part_dir = job.part_dir
    transcript_path = part_dir / "transcript.json"
    if not transcript_path.is_file():
        raise run_mod.RunError(f"transcript not found: {transcript_path}; run the pipeline first")
    audio_path = job.audio_path
    if job.render and (audio_path is None or not audio_path.is_file()):
        raise run_mod.RunError(f"no audio found for part {job.part_id}; run the pipeline first")

    job.add_event("started", stage="clips", part=job.part_id)
    t0 = time.monotonic()
    data = transcribe_mod.load_transcript(transcript_path)
    candidates = clips_mod.build_candidates(data, job.config)
    candidates = clips_mod.rerank_with_llm(candidates, job.config)
    if audio_path is not None and audio_path.is_file():
        source_info = probe_mod.probe_audio(audio_path, job.config)
        source = {
            "path": str(audio_path),
            "sha256": audit_mod.sha256_of_file(audio_path),
            "duration": source_info["duration"],
        }
    else:
        source = {"path": None, "sha256": None, "duration": None}
    clips_path = part_dir / "clips.json"
    clips_mod.write_clips_json(
        candidates,
        source=source,
        transcript_record={"path": str(transcript_path), "sha256": audit_mod.sha256_of_file(transcript_path)},
        keywords=(job.config.clips.keywords if job.config and job.config.clips else []),
        out_path=clips_path,
    )
    job.add_event("finished", stage="clips", part=job.part_id, elapsed=time.monotonic() - t0)

    if job.render:
        job.add_event("started", stage="render", part=job.part_id)
        t1 = time.monotonic()
        clips_dir = part_dir / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)
        for idx, c in enumerate(candidates, start=1):
            clips_mod.render_clip(audio_path, c["start"], c["end"], clips_dir / f"{idx}.mp3", job.config)
            clips_mod.write_clip_srt(data["segments"], c["start"], c["end"], clips_dir / f"{idx}.srt")
        job.add_event("finished", stage="render", part=job.part_id, elapsed=time.monotonic() - t1)
