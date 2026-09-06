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


def test_timed_out_job_cannot_steal_next_job_log_stream(manager, tmp_path, monkeypatch):
    """A timed-out thread may keep printing while the next job starts.

    Its output must remain in its own log, rather than being redirected into
    the newer job or restoring a stale redirect after the newer job exits.
    """
    monkeypatch.setattr(jobs_mod, "JOB_TIMEOUT_S", 0.2)
    release = threading.Event()
    call_count = {"n": 0}

    def fake_run_episode(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            print("old-job-before-timeout")
            release.wait(10)
            print("old-job-after-timeout")
            raise jobs_mod.run_mod.CancelledError("released")
        print("new-job-output")
        raise jobs_mod.run_mod.CancelledError("done")

    monkeypatch.setattr(jobs_mod.run_mod, "run_episode", fake_run_episode)
    old_job = _submit(manager, "old-ep", tmp_path)
    for _ in range(100):
        if old_job.status == "failed":
            break
        time.sleep(0.05)
    assert old_job.status == "failed"

    new_job = _submit(manager, "new-ep", tmp_path)
    for _ in range(100):
        if new_job.is_terminal():
            break
        time.sleep(0.05)
    assert new_job.status == "cancelled"

    release.set()
    for _ in range(100):
        old_log = tmp_path / "old-ep" / f"dashboard-job-{old_job.id}.log"
        if old_log.exists() and "old-job-after-timeout" in old_log.read_text(encoding="utf-8"):
            break
        time.sleep(0.05)

    old_text = old_log.read_text(encoding="utf-8")
    new_log = tmp_path / "new-ep" / f"dashboard-job-{new_job.id}.log"
    new_text = new_log.read_text(encoding="utf-8")
    assert "old-job-before-timeout" in old_text
    assert "old-job-after-timeout" in old_text
    assert "new-job-output" not in old_text
    assert "new-job-output" in new_text
    assert "old-job-after-timeout" not in new_text


def test_abandoned_thread_cannot_relock_episode_or_override_timeout_result(manager, tmp_path, monkeypatch):
    """T-0021-F1: a timed-out job's thread is abandoned, not killed, and may
    still be running when the watchdog marks the job failed. Until that
    thread actually returns: (a) resubmitting for the SAME episode must be
    rejected, so a fresh job cannot run concurrently against the same output
    files as the abandoned one; (b) the abandoned thread's own eventual
    result must not overwrite the timeout failure already recorded."""
    monkeypatch.setattr(jobs_mod, "JOB_TIMEOUT_S", 0.2)

    release = threading.Event()

    def hang_then_finish(*args, **kwargs):
        release.wait(10)
        raise jobs_mod.run_mod.CancelledError("late finish after abandonment")

    monkeypatch.setattr(jobs_mod.run_mod, "run_episode", hang_then_finish)

    job = _submit(manager, "stuck-ep", tmp_path)
    for _ in range(100):
        if job.status == "failed":
            break
        time.sleep(0.05)
    assert job.status == "failed"
    assert "time limit" in job.error

    # The abandoned thread is still blocked on `release`: a second submit for
    # the *same* episode must be rejected.
    with pytest.raises(EpisodeBusyError):
        _submit(manager, "stuck-ep", tmp_path)

    # Let the abandoned thread finish; its late (non-failure) result must not
    # clobber the timeout failure already recorded on the job.
    release.set()
    time.sleep(0.3)
    assert job.status == "failed"
    assert "time limit" in job.error

    # Once the abandoned thread has actually returned, the episode frees up.
    for _ in range(100):
        try:
            _submit(manager, "stuck-ep", tmp_path)
            break
        except EpisodeBusyError:
            time.sleep(0.05)
    else:
        pytest.fail("episode stayed locked after its abandoned thread finished")


def test_timeout_marks_episode_abandoned_before_job_goes_terminal(manager, tmp_path, monkeypatch):
    """T-0021-F2: on timeout, _abandoned_episodes must record the episode as
    busy strictly before the job's status becomes visible as terminal.
    Otherwise there is a window where `_episode_busy_locked` sees neither an
    active job (already terminal) nor an abandoned episode (not yet added),
    letting a concurrent submit/delete race the still-running thread."""
    monkeypatch.setattr(jobs_mod, "JOB_TIMEOUT_S", 0.2)

    release = threading.Event()

    def hang_then_finish(*args, **kwargs):
        release.wait(10)
        raise jobs_mod.run_mod.CancelledError("late finish after abandonment")

    monkeypatch.setattr(jobs_mod.run_mod, "run_episode", hang_then_finish)

    order: list[str] = []

    class TrackingSet(set):
        def add(self, item):
            order.append("abandoned_add")
            return super().add(item)

    manager._abandoned_episodes = TrackingSet(manager._abandoned_episodes)

    job = _submit(manager, "stuck-ep", tmp_path)
    orig_finish_if_active = job.finish_if_active

    def tracking_finish_if_active(*args, **kwargs):
        order.append("finish_if_active")
        return orig_finish_if_active(*args, **kwargs)

    job.finish_if_active = tracking_finish_if_active

    for _ in range(100):
        if job.status == "failed":
            break
        time.sleep(0.05)
    assert job.status == "failed"

    assert order == ["abandoned_add", "finish_if_active"], (
        "episode must be marked abandoned/busy before the job is exposed as "
        f"terminal, got order {order}"
    )

    release.set()
