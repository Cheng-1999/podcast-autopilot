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
from .. import run as run_mod
from .. import voice_chain as voice_chain_mod
from ..config import AppConfig

TERMINAL_STATUSES = {"done", "failed", "cancelled"}


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
        episode_yaml: Path,
        config: AppConfig,
        profile: str,
        profile_config_path: Optional[Path],
        model: str,
        out_dir: Path,
        skip: list[str],
        force: bool,
    ):
        self.id = job_id
        self.episode_id = episode_id
        self.episode_yaml = episode_yaml
        self.config = config
        self.profile = profile
        self.profile_config_path = profile_config_path
        self.model = model
        self.out_dir = out_dir
        self.skip = skip
        self.force = force

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

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "episode_id": self.episode_id,
            "profile": self.profile,
            "model": self.model,
            "force": self.force,
            "skip": self.skip,
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
        job = Job(job_id, episode_id, episode_yaml, config, profile, profile_config_path, model, out_dir, skip, force)
        with self._lock:
            self._jobs[job_id] = job
        self._queue.put(job_id)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def active_job_for_episode(self, episode_id: str) -> Optional[Job]:
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            if job.episode_id == episode_id and job.status in ("queued", "running"):
                return job
        return None

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job is None or job.is_terminal():
            return False
        job.cancel_requested = True
        return True

    def _run_worker(self) -> None:
        while True:
            job_id = self._queue.get()
            job = self.get(job_id)
            if job is None:
                continue
            if job.cancel_requested:
                job.status = "cancelled"
                job.finished_at = time.time()
                job.add_event("job_cancelled")
                continue
            self._run_job(job)

    def _run_job(self, job: Job) -> None:
        job.status = "running"
        job.started_at = time.time()
        job.add_event("job_started")

        job.log_path = Path(job.out_dir) / job.episode_id / f"dashboard-job-{job.id}.log"
        job.log_path.parent.mkdir(parents=True, exist_ok=True)

        def on_progress(evt: dict) -> None:
            job.add_event(evt["event"], stage=evt.get("stage"), part=evt.get("part"), elapsed=evt.get("elapsed", 0.0))

        try:
            with open(job.log_path, "w", encoding="utf-8") as logf:
                tee_out, tee_err = _TeeWriter(logf, job), _TeeWriter(logf, job)
                with redirect_stdout(tee_out), redirect_stderr(tee_err):
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
            job.status = "cancelled"
            job.add_event("job_cancelled")
        except (run_mod.RunError, assemble_mod.AssembleError, voice_chain_mod.VoiceChainError) as exc:
            job.status = "failed"
            job.error = str(exc)
            job.add_event("job_failed", message=str(exc))
        except Exception as exc:  # pragma: no cover - defensive: never leave a job stuck "running"
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            job.add_event("job_failed", message=job.error)
        else:
            job.status = "done"
            job.add_event("job_finished")
        finally:
            job.finished_at = time.time()
