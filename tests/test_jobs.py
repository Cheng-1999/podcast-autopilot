"""Regression coverage for JobManager reliability (T-0021).

Root cause of the observed bug ("EP5 never finishes and can't be deleted,
EP6 gets reprocessed repeatedly"): the single background worker thread had
no timeout and no per-episode de-duplication, so (a) a stage that blocks on
I/O (e.g. re-opening a huge, cloud-synced WAV file per filler candidate --
see transcribe.py's find_energy_bounds fix) left a job frozen at "running"
forever, which permanently blocked that episode's delete/re-run, and (b) a
second "Run" click for an episode already being processed was silently
queued as a duplicate job instead of being rejected.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from podcast_autopilot.server import jobs as jobs_mod
from podcast_autopilot.server.jobs import EpisodeBusyError, JobManager


@pytest.fixture
def manager():
    mgr = JobManager()
    yield mgr


def _submit(mgr: JobManager, episode_id: str, out_dir: Path) -> "jobs_mod.Job":
    return mgr.submit(
        episode_id=episode_id,
        episode_yaml=Path(f"{episode_id}.yaml"),
        config=None,
        profile="default",
        profile_config_path=None,
        model="small",
        out_dir=out_dir,
        skip=[],
        force=False,
    )


def test_submit_rejects_duplicate_while_episode_job_active(manager, tmp_path, monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def blocking_run_episode(*args, **kwargs):
        started.set()
        release.wait(10)
        raise jobs_mod.run_mod.CancelledError("stop")

    monkeypatch.setattr(jobs_mod.run_mod, "run_episode", blocking_run_episode)

    job = _submit(manager, "ep-a", tmp_path)
    assert started.wait(5), "job never started"

    with pytest.raises(EpisodeBusyError):
        _submit(manager, "ep-a", tmp_path)

    # A different episode is unaffected by ep-a's in-flight job.
    other_started = threading.Event()

    def other_run_episode(*args, **kwargs):
        other_started.set()
        raise jobs_mod.run_mod.CancelledError("stop")

    # ep-a is still active, so submitting for a different id must succeed
    # even though the (single) worker thread is currently busy with ep-a.
    other_job = _submit(manager, "ep-b", tmp_path)
    assert other_job.episode_id == "ep-b"

    release.set()
    for _ in range(100):
        if job.is_terminal():
            break
        time.sleep(0.05)
    assert job.is_terminal()


def test_worker_survives_job_setup_exception_and_keeps_draining_queue(manager, tmp_path, monkeypatch):
    """A job whose own setup (not its pipeline call) raises -- e.g. `mkdir`
    failing on a locked/cloud-sync path -- must not kill the shared worker
    thread; the next queued job (for any episode) must still run."""
    # out_dir/broken-ep is a *file*, so `mkdir(parents=True)` for its log
    # directory raises NotADirectoryError/FileExistsError.
    out_dir = tmp_path
    (out_dir / "broken-ep").write_text("not a directory")

    ran_second = threading.Event()

    def fake_run_episode(*args, **kwargs):
        ran_second.set()
        raise jobs_mod.run_mod.CancelledError("stop")

    monkeypatch.setattr(jobs_mod.run_mod, "run_episode", fake_run_episode)

    broken_job = _submit(manager, "broken-ep", out_dir)
    for _ in range(100):
        if broken_job.is_terminal():
            break
        time.sleep(0.05)
    assert broken_job.status == "failed"

    ok_job = _submit(manager, "ok-ep", tmp_path / "out2")
    assert ran_second.wait(5), "worker thread died after the first job's setup failure"
    for _ in range(100):
        if ok_job.is_terminal():
            break
        time.sleep(0.05)
    assert ok_job.status == "cancelled"


def test_stuck_job_times_out_and_frees_the_queue(manager, tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_mod, "JOB_TIMEOUT_S", 0.2)

    never_returns = threading.Event()

    def hang_forever(*args, **kwargs):
        never_returns.wait()  # blocks until the test process exits (daemon thread)
        return None

    ran_next = threading.Event()

    call_count = {"n": 0}

    def fake_run_episode(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return hang_forever()
        ran_next.set()
        raise jobs_mod.run_mod.CancelledError("stop")

    monkeypatch.setattr(jobs_mod.run_mod, "run_episode", fake_run_episode)

    stuck_job = _submit(manager, "stuck-ep", tmp_path)
    for _ in range(100):
        if stuck_job.status == "failed":
            break
        time.sleep(0.05)
    assert stuck_job.status == "failed"
    assert "time limit" in stuck_job.error

    next_job = _submit(manager, "next-ep", tmp_path)
    assert ran_next.wait(5), "queue stayed wedged behind the timed-out job"
    for _ in range(100):
        if next_job.is_terminal():
            break
        time.sleep(0.05)
