from __future__ import annotations

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


# --- uploads -----------------------------------------------------------------


def test_upload_multipart_stores_under_media_and_probes(client, tmp_path):
    c, root = client
    src_wav = tmp_path / "raw" / "clip.wav"
    generate_synthetic_audio(src_wav, duration=2.0)

    with open(src_wav, "rb") as fh:
        resp = c.post(
            "/api/uploads",
            files={"file": ("clip.wav", fh, "audio/wav")},
            data={"episode": "my-upload-ep"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["duration"] == pytest.approx(2.0, abs=0.2)
    assert body["sr"] > 0
    stored = Path(body["path"])
    assert stored.is_absolute()
    assert stored.is_file()
    assert stored.is_relative_to((root / "media" / "my-upload-ep").resolve())


def test_upload_rejects_unsupported_extension(client):
    c, _root = client
    resp = c.post(
        "/api/uploads",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={"episode": "whatever"},
    )
    assert resp.status_code == 415


def test_upload_registers_existing_path_without_copying(client, tmp_path):
    c, root = client
    src_wav = tmp_path / "external" / "existing.wav"
    generate_synthetic_audio(src_wav, duration=1.5)

    resp = c.post("/api/uploads", json={"path": str(src_wav.resolve())})
    assert resp.status_code == 200
    body = resp.json()
    assert Path(body["path"]) == src_wav.resolve()
    assert body["duration"] == pytest.approx(1.5, abs=0.2)
    assert not (root / "media").exists()


def test_upload_json_requires_absolute_existing_path(client):
    c, _root = client
    assert c.post("/api/uploads", json={"path": "relative/file.wav"}).status_code == 422
    assert c.post("/api/uploads", json={"path": "C:/does/not/exist.wav"}).status_code == 404


# --- episode creation ---------------------------------------------------------


def test_create_episode_run_and_deliverables_end_to_end(client, tmp_path):
    c, root = client
    src_wav = tmp_path / "raw" / "clip.wav"
    generate_synthetic_audio(src_wav, duration=2.0)
    with open(src_wav, "rb") as fh:
        upload = c.post("/api/uploads", files={"file": ("clip.wav", fh, "audio/wav")}).json()

    create_resp = c.post(
        "/api/episodes",
        json={"title": "Upload Episode", "episode": 42, "parts": [upload["path"]]},
    )
    assert create_resp.status_code == 200
    episode_id = create_resp.json()["id"]
    assert episode_id == "upload-episode-ep42"
    assert (root / "episodes" / f"{episode_id}.yaml").is_file()

    run_resp = c.post(f"/api/episodes/{episode_id}/run", json={"force": True})
    assert run_resp.status_code == 200
    job = _wait_for_job(c, run_resp.json()["id"])
    assert job["status"] == "done", job

    deliverables = c.get(f"/api/episodes/{episode_id}/deliverables").json()
    assert deliverables["final_mp3"] is not None
    assert deliverables["final_mp3"].startswith("/api/media/")
    assert len(deliverables["parts"]) == 1
    assert deliverables["parts"][0]["edited_wav"] is not None


def test_create_episode_duplicate_returns_409(client, tmp_path):
    c, _root = client
    src_wav = tmp_path / "dup.wav"
    generate_synthetic_audio(src_wav, duration=1.0)
    payload = {"title": "Dup", "episode": 9, "parts": [str(src_wav.resolve())]}
    assert c.post("/api/episodes", json=payload).status_code == 200
    assert c.post("/api/episodes", json=payload).status_code == 409


def test_create_episode_chapter_past_end_returns_422(client, tmp_path):
    c, _root = client
    src_wav = tmp_path / "short.wav"
    generate_synthetic_audio(src_wav, duration=2.0)
    resp = c.post(
        "/api/episodes",
        json={
            "title": "Chapter Overflow",
            "episode": 7,
            "parts": [str(src_wav.resolve())],
            "chapters": [{"start": "00:10", "title": "Too late"}],
        },
    )
    assert resp.status_code == 422


def test_update_episode_chapters_and_tags_only(client, tmp_path):
    c, root = client
    src_wav = tmp_path / "put_src.wav"
    generate_synthetic_audio(src_wav, duration=5.0)
    create_resp = c.post(
        "/api/episodes",
        json={"title": "Put Test", "episode": 3, "parts": [str(src_wav.resolve())]},
    )
    episode_id = create_resp.json()["id"]

    put_resp = c.put(
        f"/api/episodes/{episode_id}",
        json={"chapters": [{"start": "00:01", "title": "Intro"}], "tags": {"artist": "Someone"}},
    )
    assert put_resp.status_code == 200

    manifest_path = root / "episodes" / f"{episode_id}.yaml"
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert data["chapters"][0]["title"] == "Intro"
    assert data["tags"]["artist"] == "Someone"
    assert data["parts"] == [str(src_wav.resolve())]
    assert data["title"] == "Put Test"


def test_update_episode_rejects_bundled_example(client):
    c, _root = client
    resp = c.put(
        "/api/episodes/episode.example",
        json={"chapters": [], "tags": {}},
    )
    assert resp.status_code == 400


# --- peaks ---------------------------------------------------------------------


def test_peaks_returns_exact_buckets_and_is_cached(client):
    c, root = client
    run_resp = c.post("/api/episodes/episode.example/run", json={"force": True})
    _wait_for_job(c, run_resp.json()["id"])

    resp = c.get("/api/episodes/episode.example/parts/part1/peaks", params={"buckets": 50})
    assert resp.status_code == 200
    body = resp.json()
    assert body["buckets"] == 50
    assert len(body["peaks"]) == 50
    for lo, hi in body["peaks"]:
        assert lo <= hi

    cache_path = root / "out" / "episode.example" / "parts" / "part1" / "peaks.50.json"
    assert cache_path.is_file()
    mtime_before = cache_path.stat().st_mtime_ns

    resp2 = c.get("/api/episodes/episode.example/parts/part1/peaks", params={"buckets": 50})
    assert resp2.status_code == 200
    assert resp2.json() == body
    assert cache_path.stat().st_mtime_ns == mtime_before


def test_peaks_falls_back_to_source_before_run(client):
    c, _root = client
    resp = c.get("/api/episodes/episode.example/parts/part1/peaks", params={"buckets": 10})
    assert resp.status_code == 200
    assert len(resp.json()["peaks"]) == 10


# --- clips ---------------------------------------------------------------------


def test_clips_post_writes_clips_json_and_get_reads_it(client):
    c, root = client
    run_resp = c.post("/api/episodes/episode.example/run", json={"force": True})
    _wait_for_job(c, run_resp.json()["id"])

    resp = c.post("/api/episodes/episode.example/parts/part1/clips", json={"render": False})
    assert resp.status_code == 200
    job = _wait_for_job(c, resp.json()["id"])
    assert job["status"] == "done", job

    clips_path = root / "out" / "episode.example" / "parts" / "part1" / "clips.json"
    assert clips_path.is_file()

    get_resp = c.get("/api/episodes/episode.example/parts/part1/clips")
    assert get_resp.status_code == 200
    assert "candidates" in get_resp.json()


def test_clips_post_without_transcript_is_404(client):
    c, _root = client
    resp = c.post("/api/episodes/episode.example/parts/part1/clips", json={"render": False})
    assert resp.status_code == 404
