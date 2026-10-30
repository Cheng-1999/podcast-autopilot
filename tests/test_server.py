from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from podcast_autopilot.audit import audit_plan, sha256_of_file
from podcast_autopilot.ffmpeg import generate_synthetic_audio
from podcast_autopilot.plan import EditPlan, PlanItem, ProfileInfo, SourceInfo
from podcast_autopilot.server import create_app
from podcast_autopilot.server.routes import _carve_manual_cut


def _make_project(tmp_path: Path) -> Path:
    examples = tmp_path / "examples"
    examples.mkdir()
    for name in ("part1.wav", "part2.wav"):
        generate_synthetic_audio(examples / name, duration=2.0)
    manifest = {"title": "Test Episode", "episode": 1, "parts": ["part1.wav", "part2.wav"]}
    (examples / "episode.example.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return tmp_path


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # cli._resolve_profile_config_path looks for profiles/ relative to CWD,
    # exactly like dashboard.ps1's uvicorn (started with CWD = repo root).
    monkeypatch.chdir(tmp_path)
    project_root = _make_project(tmp_path)
    app = create_app(project_root=project_root)
    with TestClient(app) as test_client:
        yield test_client, project_root


def _wait_for_job(client: TestClient, job_id: str, timeout: float = 180.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] in ("done", "failed", "cancelled"):
            return body
        time.sleep(0.2)
    raise TimeoutError(f"job {job_id} did not finish in time")


def _sse_events(text: str) -> list[dict]:
    events = []
    for block in text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    return events


def test_health_reports_ffmpeg_and_models(client):
    c, _root = client
    resp = c.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "ffmpeg_ok" in body
    assert set(body["whisper_models"]) == {"small", "medium", "large-v3"}


def test_shutdown_responds_ok_and_schedules_process_exit(client, monkeypatch):
    c, _root = client
    exit_calls: list[int] = []
    # os._exit would kill the test process itself, so replace it with a spy
    # and just confirm the endpoint schedules a call to it.
    monkeypatch.setattr("podcast_autopilot.server.routes.os._exit", exit_calls.append)
    monkeypatch.setattr("podcast_autopilot.server.routes.time.sleep", lambda _seconds: None)

    resp = c.post("/api/shutdown")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    deadline = time.monotonic() + 5.0
    while not exit_calls and time.monotonic() < deadline:
        time.sleep(0.05)
    assert exit_calls == [0]


def test_list_episodes_sees_bundled_example(client):
    c, _root = client
    resp = c.get("/api/episodes")
    assert resp.status_code == 200
    episodes = resp.json()
    example = next(e for e in episodes if e["id"] == "episode.example")
    assert example["example"] is True
    assert example["status"] == "never-run"


def test_delete_episode_removes_manifest_output_and_media(client):
    c, root = client
    episodes_dir = root / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = episodes_dir / "my-ep.yaml"
    manifest_path.write_text(
        yaml.safe_dump({"title": "My Ep", "episode": 1, "parts": ["part1.wav"]}),
        encoding="utf-8",
    )
    out_dir = root / "out" / "my-ep"
    out_dir.mkdir(parents=True)
    (out_dir / "RUN_REPORT.md").write_text("# Run Report: my-ep", encoding="utf-8")
    media_dir = root / "media" / "my-ep"
    media_dir.mkdir(parents=True)
    (media_dir / "part1.wav").write_bytes(b"fake")

    resp = c.delete("/api/episodes/my-ep")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert not manifest_path.exists()
    assert not out_dir.exists()
    assert not media_dir.exists()

    assert c.get("/api/episodes/my-ep").status_code == 404


def test_delete_episode_unknown_id_is_404(client):
    c, _root = client
    assert c.delete("/api/episodes/does-not-exist").status_code == 404


def test_delete_episode_rejects_bundled_example(client):
    c, root = client
    resp = c.delete("/api/episodes/episode.example")
    assert resp.status_code == 400
    assert (root / "examples" / "episode.example.yaml").exists()


def test_delete_episode_rejects_while_job_running(client):
    c, root = client
    episodes_dir = root / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    (episodes_dir / "running-ep.yaml").write_text(
        yaml.safe_dump({"title": "Running Ep", "episode": 1, "parts": ["../examples/part1.wav"]}),
        encoding="utf-8",
    )

    run_resp = c.post("/api/episodes/running-ep/run", json={"force": True})
    job_id = run_resp.json()["id"]
    try:
        resp = c.delete("/api/episodes/running-ep")
        assert resp.status_code == 409
    finally:
        c.post(f"/api/jobs/{job_id}/cancel")
        _wait_for_job(c, job_id)


def test_delete_episode_rejects_unsafe_id(client):
    c, root = client
    # a manifest file literally named "...yaml" glob-matches "*.yaml" with a
    # Path.stem of "..", which -- without validation -- would resolve
    # out/<id> and media/<id> to the project root and delete far outside the
    # episode's own directory.
    episodes_dir = root / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = episodes_dir / "...yaml"
    manifest_path.write_text(
        yaml.safe_dump({"title": "Traversal", "episode": 1, "parts": ["part1.wav"]}),
        encoding="utf-8",
    )
    sentinel = root / "sentinel.txt"
    sentinel.write_text("do not delete me", encoding="utf-8")

    # percent-encoded so the test client's own URL normalization (which would
    # otherwise collapse ".." into the parent path segment before the request
    # is even sent) doesn't mask what the server receives: uvicorn decodes
    # %2e%2e to a literal ".." path segment, exactly as a raw HTTP client can.
    resp = c.delete("/api/episodes/%2e%2e")
    assert resp.status_code == 400
    assert manifest_path.exists()
    assert sentinel.exists()


def test_delete_episode_blocks_concurrent_job_submission(client):
    c, root = client
    from podcast_autopilot.server.jobs import EpisodeDeletingError

    episodes_dir = root / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    (episodes_dir / "race-ep.yaml").write_text(
        yaml.safe_dump({"title": "Race Ep", "episode": 1, "parts": ["../examples/part1.wav"]}),
        encoding="utf-8",
    )

    app = c.app
    job_manager = app.state.job_manager
    assert job_manager.begin_delete("race-ep") is True
    try:
        with pytest.raises(EpisodeDeletingError):
            job_manager.submit(
                episode_id="race-ep",
                episode_yaml=episodes_dir / "race-ep.yaml",
                config=None,
                profile="default",
                profile_config_path=None,
                model="small",
                out_dir=root / "out",
                skip=[],
                force=True,
            )
        resp = c.post("/api/episodes/race-ep/run", json={"force": True})
        assert resp.status_code == 409
    finally:
        job_manager.end_delete("race-ep")


def test_run_job_completes_and_sse_covers_every_stage(client):
    c, _root = client
    resp = c.post("/api/episodes/episode.example/run", json={"force": True})
    assert resp.status_code == 200
    job_id = resp.json()["id"]

    events_resp = c.get(f"/api/jobs/{job_id}/events")
    assert events_resp.status_code == 200
    events = _sse_events(events_resp.text)

    job = _wait_for_job(c, job_id)
    assert job["status"] == "done", job

    started = {e["stage"] for e in events if e["event"] == "started"}
    finished = {e["stage"] for e in events if e["event"] == "finished"}
    for stage in ("probe", "clean", "plan-pauses", "transcribe", "plan-fillers", "audit", "apply", "assemble"):
        assert stage in started, (stage, events)
        assert stage in finished, (stage, events)

    detail = c.get("/api/episodes/episode.example").json()
    assert detail["status"] in ("done", "needs-review")
    assert detail["reapply_command"]
    assert len(detail["parts_detail"]) == 2


def test_plan_put_persists_valid_change_and_rejects_invalid_without_writing(client):
    c, root = client
    run_resp = c.post("/api/episodes/episode.example/run", json={"force": True})
    _wait_for_job(c, run_resp.json()["id"])

    plan_path = root / "out" / "episode.example" / "parts" / "part1" / "plan.json"
    original_text = plan_path.read_text(encoding="utf-8")
    original = json.loads(original_text)
    keep_item = next(it for it in original["items"] if it["kind"] == "keep")

    broken = json.loads(original_text)
    broken["items"].append({
        "id": "bad-overlap", "kind": "cut", "start": keep_item["start"], "end": keep_item["end"],
        "reason": "manufactured overlap for the 422 test", "enabled": False,
    })
    plan_path.write_text(json.dumps(broken), encoding="utf-8")

    bad_resp = c.put(
        "/api/episodes/episode.example/parts/part1/plan",
        json=[{"id": keep_item["id"], "enabled": True}],
    )
    assert bad_resp.status_code == 422
    assert bad_resp.json()["errors"]
    assert json.loads(plan_path.read_text(encoding="utf-8")) == broken

    plan_path.write_text(original_text, encoding="utf-8")
    ok_resp = c.put(
        "/api/episodes/episode.example/parts/part1/plan",
        json=[{"id": keep_item["id"], "enabled": True}],
    )
    assert ok_resp.status_code == 200
    saved = json.loads(plan_path.read_text(encoding="utf-8"))
    assert any(it["id"] == keep_item["id"] and it["enabled"] is True for it in saved["items"])


def test_carve_manual_cut_on_cut_only_plan_leaves_existing_cuts_untouched():
    # Real pipeline output for a part with no explicit "keep" items (e.g.
    # plan-pauses' output): nothing here is a "keep" item, so nothing should
    # be split -- audit_plan's own overlap check is what rejects a genuine
    # conflict with an existing cut.
    items = [
        PlanItem(id="cut-0001", kind="cut", start=0.0, end=1.0, reason="pause"),
        PlanItem(id="cut-0002", kind="cut", start=5.0, end=6.0, reason="pause"),
    ]
    carved = _carve_manual_cut(items, start=2.0, end=3.0)
    assert carved == items


def test_carve_manual_cut_splits_and_drops_keep_items():
    items = [
        PlanItem(id="keep-0001", kind="keep", start=0.0, end=10.0, reason="identity"),
    ]

    # Cut fully inside the keep item: split into a "before" and "after" piece.
    split = _carve_manual_cut(items, start=4.0, end=6.0)
    assert {(it.id, it.start, it.end) for it in split} == {
        ("keep-0001-a", 0.0, 4.0),
        ("keep-0001-b", 6.0, 10.0),
    }

    # Cut covering the whole keep item: it disappears entirely.
    covered = _carve_manual_cut(items, start=0.0, end=10.0)
    assert covered == []

    # Cut touching only the tail: only a "before" piece remains.
    tail = _carve_manual_cut(items, start=8.0, end=10.0)
    assert [(it.id, it.start, it.end) for it in tail] == [("keep-0001-a", 0.0, 8.0)]


def test_carve_manual_cut_splits_and_drops_overlapping_filler_items():
    # T-0021-F1 round-1 review: a filler item (a proposal nested inside a
    # keep span, see audit.ALLOWED_KINDS) left untouched by a manual/AI cut
    # that overlaps it would end up pointing at audio the cut just removed --
    # audit_plan then rejects the whole plan as "not inside any keep span".
    # The filler item must be trimmed/split at the same boundaries as the
    # keep item it lives in.
    items = [
        PlanItem(id="keep-0001", kind="keep", start=0.0, end=10.0, reason="identity"),
        PlanItem(id="filler-0001", kind="filler", start=4.0, end=6.0, reason="um"),
    ]

    # Cut fully covering the filler (and only part of the keep item): the
    # filler is dropped entirely, same as a keep item would be.
    covered = _carve_manual_cut(items, start=3.0, end=7.0)
    assert {(it.id, it.start, it.end) for it in covered} == {
        ("keep-0001-a", 0.0, 3.0),
        ("keep-0001-b", 7.0, 10.0),
    }

    # Cut overlapping only the tail half of the filler: filler is trimmed to
    # its surviving "before" piece, at the same boundary as the keep split.
    tail = _carve_manual_cut(items, start=5.0, end=8.0)
    assert {(it.id, it.start, it.end) for it in tail} == {
        ("keep-0001-a", 0.0, 5.0),
        ("keep-0001-b", 8.0, 10.0),
        ("filler-0001-a", 4.0, 5.0),
    }

    # Cut fully inside the filler: filler splits into "before" and "after"
    # pieces, both still nested inside their respective keep splits.
    split = _carve_manual_cut(items, start=4.5, end=5.5)
    assert {(it.id, it.start, it.end) for it in split} == {
        ("keep-0001-a", 0.0, 4.5),
        ("keep-0001-b", 5.5, 10.0),
        ("filler-0001-a", 4.0, 4.5),
        ("filler-0001-b", 5.5, 6.0),
    }


def test_manual_cut_overlapping_filler_item_passes_audit(tmp_path: Path):
    # End-to-end version of the carve fix above: a manual cut overlapping an
    # existing filler item must produce a plan that `audit_plan` accepts, not
    # one it rejects for the filler no longer being inside a keep span.
    audio_path = tmp_path / "source.bin"
    audio_path.write_bytes(b"not really audio, just needs stable bytes for a hash" * 100)
    source = SourceInfo(path=str(audio_path), sha256=sha256_of_file(audio_path), duration=10.0, sr=44100, channels=1)
    items = [
        PlanItem(id="keep-0001", kind="keep", start=0.0, end=10.0, reason="identity"),
        PlanItem(id="filler-0001", kind="filler", start=4.0, end=6.0, reason="um", enabled=True),
    ]
    plan = EditPlan(
        schema="podcast-autopilot.edit-plan/v1",
        created="2026-09-07T00:00:00+00:00",
        source=source,
        profile=ProfileInfo(name="test", max_removed_fraction=0.5),
        items=items,
    )

    carved = _carve_manual_cut(plan.items, start=5.0, end=8.0)
    new_item = PlanItem(id="manual-0001", kind="cut", start=5.0, end=8.0, reason="manual", enabled=True)
    plan.items = sorted([*carved, new_item], key=lambda it: it.start)

    result = audit_plan(plan, audio_path)
    assert result.ok, result.errors


def test_add_manual_cut_persists_and_rejects_overlap(client):
    c, root = client
    run_resp = c.post("/api/episodes/episode.example/run", json={"force": True})
    _wait_for_job(c, run_resp.json()["id"])

    plan_path = root / "out" / "episode.example" / "parts" / "part1" / "plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    keep_item = next(it for it in plan["items"] if it["kind"] == "keep")
    duration = keep_item["end"] - keep_item["start"]

    resp = c.post(
        "/api/episodes/episode.example/parts/part1/plan/cuts",
        json={"start": 0.0, "end": min(0.05, duration / 4), "reason": "test manual cut"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["id"] == "manual-0001"

    saved = json.loads(plan_path.read_text(encoding="utf-8"))
    added = next(it for it in saved["items"] if it["id"] == "manual-0001")
    assert added["kind"] == "cut"
    assert added["reason"] == "test manual cut"
    assert added["enabled"] is True

    # A second cut overlapping the one just added must be rejected without
    # touching the file (audit_plan's overlap check is fail-closed).
    before = plan_path.read_text(encoding="utf-8")
    bad_resp = c.post(
        "/api/episodes/episode.example/parts/part1/plan/cuts",
        json={"start": 0.0, "end": min(0.05, duration / 4)},
    )
    assert bad_resp.status_code == 422
    assert bad_resp.json()["errors"]
    assert plan_path.read_text(encoding="utf-8") == before

    # end <= start is a plain 422, not a 500.
    invalid_resp = c.post(
        "/api/episodes/episode.example/parts/part1/plan/cuts",
        json={"start": 1.0, "end": 1.0},
    )
    assert invalid_resp.status_code == 422


def test_ai_suggest_cuts_rejects_when_not_configured(client):
    c, root = client
    run_resp = c.post("/api/episodes/episode.example/run", json={"force": True})
    _wait_for_job(c, run_resp.json()["id"])

    resp = c.post("/api/episodes/episode.example/parts/part1/plan/ai-suggest", json={})
    assert resp.status_code == 400
    assert "ai_suggest" in resp.json()["detail"]


def test_ai_suggest_cuts_returns_validated_candidates(client, monkeypatch):
    c, root = client
    run_resp = c.post("/api/episodes/episode.example/run", json={"force": True})
    _wait_for_job(c, run_resp.json()["id"])

    (root / "profiles").mkdir(exist_ok=True)
    (root / "profiles" / "default.yaml").write_text(
        yaml.safe_dump({"ai_suggest": {"command": ["fake-cli", "-p"]}}), encoding="utf-8"
    )

    plan_path = root / "out" / "episode.example" / "parts" / "part1" / "plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    keep_item = next(it for it in plan["items"] if it["kind"] == "keep")
    duration = keep_item["end"] - keep_item["start"]
    good_end = min(0.1, duration / 4)

    from podcast_autopilot import ai_suggest as ai_suggest_mod

    def fake_run_ai_suggest(command, prompt, timeout_s):
        assert command == ["fake-cli", "-p"]
        return [
            ai_suggest_mod.CutSuggestion(start=0.0, end=good_end, reason="redundant retake"),
            ai_suggest_mod.CutSuggestion(start=0.0, end=good_end, reason="duplicate of the one above"),
        ]

    monkeypatch.setattr(ai_suggest_mod, "run_ai_suggest", fake_run_ai_suggest)

    resp = c.post("/api/episodes/episode.example/parts/part1/plan/ai-suggest", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert len(body["suggestions"]) == 2
    # Each suggestion is audited independently against the plan as currently
    # saved on disk (not against previously-listed suggestions), so two
    # suggestions that happen to overlap each other are both reported valid
    # here -- accepting one via plan/cuts is what would make the other
    # (now-overlapping) one rejected on a later request.
    assert body["suggestions"][0]["valid"] is True
    assert body["suggestions"][1]["valid"] is True

    # plan.json on disk must be untouched: suggestions are never auto-applied.
    assert json.loads(plan_path.read_text(encoding="utf-8")) == plan


def test_media_range_request_returns_partial_content(client):
    c, root = client
    run_resp = c.post("/api/episodes/episode.example/run", json={"force": True})
    _wait_for_job(c, run_resp.json()["id"])

    resp = c.get("/api/media/episode.example/parts/part1/part1.clean.wav", headers={"Range": "bytes=0-99"})
    assert resp.status_code == 206
    assert len(resp.content) == 100
    assert resp.headers["Content-Range"].startswith("bytes 0-99/")
    assert resp.headers["Accept-Ranges"] == "bytes"


def test_media_path_traversal_is_rejected(client):
    c, _root = client
    resp = c.get("/api/media/episode.example/..%2F..%2Fpyproject.toml")
    assert resp.status_code == 404


def test_media_unknown_episode_is_404(client):
    c, _root = client
    resp = c.get("/api/media/does-not-exist/whatever.wav")
    assert resp.status_code == 404


def test_get_report_and_transcript(client):
    c, _root = client
    # Report before run is 404
    assert c.get("/api/episodes/episode.example/report").status_code == 404
    assert c.get("/api/episodes/episode.example/parts/part1/transcript").status_code == 404

    run_resp = c.post("/api/episodes/episode.example/run", json={"force": True})
    _wait_for_job(c, run_resp.json()["id"])

    report_resp = c.get("/api/episodes/episode.example/report")
    assert report_resp.status_code == 200
    assert "# Run Report: episode.example" in report_resp.text

    transcript_resp = c.get("/api/episodes/episode.example/parts/part1/transcript")
    assert transcript_resp.status_code == 200
    transcript = transcript_resp.json()
    assert "segments" in transcript


def test_job_cancel_queued_or_running(client):
    c, _root = client
    resp = c.post("/api/episodes/episode.example/run", json={"force": True})
    job_id = resp.json()["id"]
    cancel_resp = c.post(f"/api/jobs/{job_id}/cancel")
    assert cancel_resp.status_code == 200
    body = _wait_for_job(c, job_id)
    assert body["status"] in ("cancelled", "done")


def test_spa_fallback_serves_index_and_assets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project_root = _make_project(tmp_path)
    web_dist = project_root / "web" / "dist"
    web_dist.mkdir(parents=True)
    (web_dist / "index.html").write_text("<!doctype html><html><body>SPA</body></html>", encoding="utf-8")
    assets_dir = web_dist / "assets"
    assets_dir.mkdir()
    (assets_dir / "main.js").write_text("console.log('loaded');", encoding="utf-8")

    app = create_app(project_root=project_root)
    with TestClient(app) as c:
        root_resp = c.get("/")
        assert root_resp.status_code == 200
        assert "SPA" in root_resp.text

        route_resp = c.get("/episodes/episode.example")
        assert route_resp.status_code == 200
        assert "SPA" in route_resp.text

        asset_resp = c.get("/assets/main.js")
        assert asset_resp.status_code == 200
        assert "console.log" in asset_resp.text

        api_missing = c.get("/api/nonexistent")
        assert api_missing.status_code == 404
        assert api_missing.json() == {"detail": "not found"}


def test_loop_exception_handler_silences_benign_proactor_reset(monkeypatch, tmp_path):
    from podcast_autopilot.server.app import _loop_exception_handler

    calls = []
    loop = type("FakeLoop", (), {"default_exception_handler": lambda self, ctx: calls.append(ctx)})()

    reset_exc = ConnectionResetError("forcibly closed")
    reset_exc.winerror = 10054
    _loop_exception_handler(loop, {"exception": reset_exc, "message": "..."})
    assert calls == []

    other_exc = ConnectionResetError("forcibly closed")
    other_exc.winerror = 10053
    _loop_exception_handler(loop, {"exception": other_exc, "message": "..."})
    assert len(calls) == 1

    value_exc = ValueError("unrelated")
    _loop_exception_handler(loop, {"exception": value_exc, "message": "..."})
    assert len(calls) == 2

    _loop_exception_handler(loop, {"message": "no exception key"})
    assert len(calls) == 3


@pytest.mark.skipif(sys.platform != "win32", reason="ProactorEventLoop exception handler is Windows-only")
def test_lifespan_installs_loop_exception_handler_on_windows():
    from podcast_autopilot.server.app import _lifespan, _loop_exception_handler

    async def run() -> None:
        async with _lifespan(None):
            loop = asyncio.get_running_loop()
            assert loop.get_exception_handler() is _loop_exception_handler

    asyncio.run(run())
