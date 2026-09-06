from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from podcast_autopilot.ffmpeg import generate_synthetic_audio
from podcast_autopilot.server import create_app


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
    assert set(body["whisper_models"]) == {"small", "medium"}


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
