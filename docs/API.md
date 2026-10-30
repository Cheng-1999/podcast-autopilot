# podcast-autopilot Dashboard API

FastAPI backend documentation for the podcast-autopilot dashboard. All API routes are prefixed with `/api`.
When `web/dist` exists, all other non-API routes serve static assets with an SPA `index.html` fallback.

---

## Table of Contents

- [Overview](#overview)
- [System & Health](#system--health)
  - [`GET /api/health`](#get-apihealth)
- [Uploads](#uploads)
  - [`POST /api/uploads`](#post-apiuploads)
- [Episodes](#episodes)
  - [`GET /api/episodes`](#get-apiepisodes)
  - [`POST /api/episodes`](#post-apiepisodes)
  - [`PUT /api/episodes/{id}`](#put-apiepisodesid)
  - [`GET /api/episodes/{id}`](#get-apiepisodesid)
  - [`GET /api/episodes/{id}/report`](#get-apiepisodesidreport)
  - [`POST /api/episodes/{id}/run`](#post-apiepisodesidrun)
  - [`GET /api/episodes/{id}/deliverables`](#get-apiepisodesiddeliverables)
- [Jobs & Real-time Progress](#jobs--real-time-progress)
  - [`GET /api/jobs/{id}`](#get-apijobsid)
  - [`GET /api/jobs/{id}/events`](#get-apijobsidevents)
  - [`POST /api/jobs/{id}/cancel`](#post-apijobsidcancel)
- [Part Plans & Transcripts](#part-plans--transcripts)
  - [`GET /api/episodes/{id}/parts/{part}/plan`](#get-apiepisodesidpartspartplan)
  - [`PUT /api/episodes/{id}/parts/{part}/plan`](#put-apiepisodesidpartspartplan)
  - [`POST /api/episodes/{id}/parts/{part}/plan/cuts`](#post-apiepisodesidpartspartplancuts)
  - [`POST /api/episodes/{id}/parts/{part}/plan/ai-suggest`](#post-apiepisodesidpartspartplanai-suggest)
  - [`GET /api/episodes/{id}/parts/{part}/transcript`](#get-apiepisodesidpartsparttranscript)
  - [`GET /api/episodes/{id}/parts/{part}/peaks`](#get-apiepisodesidpartspartpeaks)
- [Clips](#clips)
  - [`GET /api/episodes/{id}/parts/{part}/clips`](#get-apiepisodesidpartspartclips)
  - [`POST /api/episodes/{id}/parts/{part}/clips`](#post-apiepisodesidpartspartclips)
- [Media Serving](#media-serving)
  - [`GET /api/media/{episode}/{path}`](#get-apimediaepisodepath)
- [SPA Static Serving](#spa-static-serving)

---

## Overview

- **Base URL**: `http://localhost:8765/api` (or `http://<LAN_IP>:8765/api`)
- **Port**: 8765 by default (configurable via `.\dashboard.ps1 -Port <port>`)
- **Authentication**: None (LAN-only)
- **CORS**: Same-origin when served by `dashboard.ps1` (or Vite proxy in dev)

---

## System & Health

### `GET /api/health`

Reports system dependencies, installed ffmpeg/ffprobe binaries, cached whisper models, and free disk space.

#### Response (200 OK)

```json
{
  "ffmpeg": "C:\\Users\\a8878\\AppData\\Local\\Microsoft\\WinGet\\Packages\\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\\ffmpeg-9.0.1-full_build\\bin\\ffmpeg.EXE",
  "ffprobe": "C:\\Users\\a8878\\AppData\\Local\\Microsoft\\WinGet\\Packages\\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\\ffmpeg-9.0.1-full_build\\bin\\ffprobe.EXE",
  "ffmpeg_ok": true,
  "whisper_models": {
    "small": true,
    "medium": true,
    "large-v3": false
  },
  "free_disk_gb": 633.4
}
```

---

## Uploads

### `POST /api/uploads`

Two request modes, selected by `Content-Type`.

**Multipart** (`multipart/form-data`): stores a new audio file under `media/<episode>/<original name>`.
- `file` *(required)*: the audio file. Extension must be one of `.wav`, `.mp3`, `.flac`, `.m4a` (case-insensitive); anything else is rejected with `415`.
- `episode` *(optional form field)*: subdirectory name under `media/` (defaults to `_uploads`). Sanitized to its base name only (no path traversal).

**JSON** (`application/json`): registers an existing local file without copying it.
```json
{ "path": "C:\\Users\\me\\Desktop\\podcast\\raw-take.wav" }
```
`path` must be absolute and must already exist on this machine.

Both modes probe the resulting file with `probe_mod.probe_audio` and return the same shape. The returned `path` is always absolute, so it can be passed straight into `parts` on `POST /api/episodes` (episode manifests resolve relative part paths against the manifest's own directory, so an absolute path is the only form that works regardless of where the part physically lives).

#### Response (200 OK)

```json
{
  "path": "C:\\Users\\a8878\\OneDrive\\桌面\\podcast-autopilot\\media\\my-episode\\raw-take.wav",
  "duration": 2431.7,
  "sr": 44100,
  "channels": 1
}
```

#### Error Responses
- `422 Unprocessable Entity`: missing `file`/`path`, or a JSON `path` that is not absolute.
- `404 Not Found`: JSON `path` does not exist.
- `415 Unsupported Media Type`: multipart upload has a disallowed extension, or the stored/registered file fails to probe as audio.

---

## Episodes

### `GET /api/episodes`

Lists all manifests discovered under `episodes/*.yaml` (real user episodes) and `examples/*.yaml` (bundled fixtures). If an ID exists in both, the one from `episodes/` takes precedence.

#### Response (200 OK)

```json
[
  {
    "id": "episode.example",
    "path": "examples\\episode.example.yaml",
    "example": true,
    "title": "Episode 3",
    "episode": 3,
    "parts": [
      "example-part-1.wav",
      "example-part-2.wav"
    ],
    "error": null,
    "status": "done",
    "last_run_time": 1788623041.63,
    "final_mp3": "out\\episode.example\\ep03\\ep03.mp3",
    "duration": 40.5,
    "lufs": -16.41,
    "job_id": null
  },
  {
    "id": "ep3.local",
    "path": "examples\\ep3.local.yaml",
    "example": true,
    "title": "Episode 3",
    "episode": 3,
    "parts": [
      "C:\\Users\\a8878\\OneDrive\\桌面\\podcast\\EP3-1.wav",
      "C:\\Users\\a8878\\OneDrive\\桌面\\podcast\\EP3-2.wav"
    ],
    "error": null,
    "status": "needs-review",
    "last_run_time": 1788617652.55,
    "final_mp3": "out\\ep3.local\\ep03\\ep03.mp3",
    "duration": 2426.98,
    "lufs": -17.46,
    "job_id": null
  }
]
```

#### Status Values
- `never-run`: No outputs exist yet for this episode manifest.
- `running`: A background job is currently queued or executing for this episode.
- `needs-review`: Pipeline finished with disabled filler proposals requiring human review.
- `done`: Pipeline completed without unreviewed filler items.
- `failed`: Pipeline run failed or was interrupted.
- `invalid`: Manifest YAML could not be loaded or parsed.

---

### `POST /api/episodes`

Creates a new episode manifest at `episodes/<slug>.yaml`, where `<slug>` is derived from `title` and `episode`
(e.g. `"Deep Dive" episode 3` → `deep-dive-ep03`). Body mirrors `assemble_mod.EpisodeManifest`
(`title`, `episode`, `parts[]`, `intro`, `outro`, `bgm`, `chapters[]`, `tags`); `parts` entries are typically the
absolute paths returned by `POST /api/uploads`.

Every part must already exist and probe as audio; every chapter's `start` must fall strictly before the
sum of the parts' durations (an approximation used only at creation time — the real bound, including
intro/outro/bgm, is enforced again at assembly).

#### Request Body

```json
{
  "title": "Deep Dive",
  "episode": 3,
  "parts": ["C:\\Users\\a8878\\OneDrive\\桌面\\podcast-autopilot\\media\\my-episode\\raw-take.wav"],
  "chapters": [{ "start": "00:00", "title": "Intro" }]
}
```

#### Response (200 OK)

```json
{ "id": "deep-dive-ep03", "path": "episodes\\deep-dive-ep03.yaml" }
```

#### Error Responses
- `422 Unprocessable Entity`: body fails `EpisodeManifest` validation, a part does not exist/probe, or a
  chapter starts at or after the parts' total duration.
- `409 Conflict`: an episode with the same id already exists (in `episodes/` or `examples/`).

---

### `PUT /api/episodes/{id}`

Updates only `chapters` and `tags` on an existing **real** (non-bundled) episode manifest; `title`,
`episode` and `parts` cannot be changed once created. Chapters are re-validated against the parts'
total duration exactly as in `POST /api/episodes`.

#### Request Body

```json
{
  "chapters": [{ "start": "00:00", "title": "Intro" }, { "start": "05:00", "title": "Main topic" }],
  "tags": { "artist": "Me", "album": "My Podcast" }
}
```

#### Response (200 OK)

```json
{ "id": "deep-dive-ep03", "path": "episodes\\deep-dive-ep03.yaml" }
```

#### Error Responses
- `400 Bad Request`: `{id}` is a bundled example manifest (`examples/*.yaml`), which is read-only.
- `404 Not Found`: episode not found.
- `422 Unprocessable Entity`: manifest invalid, or a chapter starts at or after the parts' total duration.

---

### `GET /api/episodes/{id}`

Returns full episode detail, including per-part stage tables parsed from `RUN_REPORT.md`, disabled filler proposals, assembly outcomes, and the CLI reapply command.

#### Response (200 OK)

```json
{
  "id": "episode.example",
  "path": "examples\\episode.example.yaml",
  "example": true,
  "title": "Episode 3",
  "episode": 3,
  "parts": [
    "example-part-1.wav",
    "example-part-2.wav"
  ],
  "error": null,
  "status": "done",
  "last_run_time": 1788623041.63,
  "final_mp3": "out\\episode.example\\ep03\\ep03.mp3",
  "duration": 40.5,
  "lufs": -16.41,
  "job_id": null,
  "report_available": true,
  "parts_detail": [
    {
      "stem": "example-part-1",
      "source": "examples\\example-part-1.wav",
      "loudness_before": "-23.00 LUFS",
      "loudness_after": "-16.00 LUFS",
      "seconds_removed": 1.25,
      "transcript": "out\\episode.example\\parts\\example-part-1\\transcript.json",
      "plan": "out\\episode.example\\parts\\example-part-1\\plan.json",
      "stages": [
        { "name": "probe", "status": "ran", "elapsed": 0.05 },
        { "name": "clean", "status": "ran", "elapsed": 0.42 },
        { "name": "plan-pauses", "status": "ran", "elapsed": 0.12 },
        { "name": "transcribe", "status": "ran", "elapsed": 1.85 },
        { "name": "plan-fillers", "status": "ran", "elapsed": 0.18 },
        { "name": "audit", "status": "ran", "elapsed": 0.04 },
        { "name": "apply", "status": "ran", "elapsed": 0.35 }
      ],
      "disabled_filler_proposals": [
        {
          "id": "filler-12",
          "start": 14.52,
          "end": 14.98,
          "reason": "confidence below threshold"
        }
      ]
    }
  ],
  "assembly": {
    "status": "ran",
    "output": "out\\episode.example\\ep03\\ep03.mp3",
    "receipt": "out\\episode.example\\ep03\\receipt.json",
    "duration": 40.5,
    "loudness": "-16.41 LUFS"
  },
  "reapply_command": "python -m podcast_autopilot run examples\\episode.example.yaml --profile default"
}
```

#### Error Responses
- `404 Not Found`: Episode with ID `{id}` not found.

---

### `DELETE /api/episodes/{id}`

Deletes an episode: its manifest (`episodes/{id}.yaml`), generated output (`out/{id}/`), and uploaded media (`media/{id}/`). Irreversible.

#### Response (200 OK)

```json
{ "ok": true }
```

#### Error Responses
- `400 Bad Request`: `{id}` is a bundled example manifest (`examples/*.yaml`), which cannot be deleted.
- `404 Not Found`: Episode with ID `{id}` not found.
- `409 Conflict`: A job is currently running for this episode; cancel it first.

---

### `GET /api/episodes/{id}/report`

Returns the raw markdown contents of `RUN_REPORT.md` (`text/plain; charset=utf-8`).

#### Response (200 OK)

```markdown
# Run Report: episode.example

- Generated: 2026-09-06T00:54:01.123456+00:00
- Episode manifest: `examples\episode.example.yaml`
- Profile: `default` (built-in defaults)

## Part: example-part-1
...
```

#### Error Responses
- `404 Not Found`: Report does not exist (run has not been executed yet).

---

### `POST /api/episodes/{id}/run`

Enqueues a background pipeline execution job for episode `{id}`. Jobs are strictly serialized in a single background worker thread. Stdout and stderr are captured to `out/{id}/dashboard-job-{job_id}.log`.

#### Request Body

```json
{
  "profile": "default",
  "model": "small",
  "force": false,
  "skip": ["probe", "clean"]
}
```

- `profile` *(string, optional, default: "default")*: Profile name matching `profiles/<profile>.yaml` or built-in defaults.
- `model` *(string, optional)*: Whisper model size (`"small"`, `"medium"`, or `"large-v3"`). If omitted, uses profile default.
- `force` *(boolean, optional, default: false)*: Force re-execution of cached stages.
- `skip` *(array of strings, optional)*: List of stages to skip (`"probe"`, `"clean"`, `"plan-pauses"`, `"transcribe"`, `"plan-fillers"`, `"audit"`, `"apply"`, `"assemble"`).

#### Response (200 OK)

```json
{
  "id": "4a7b9c1d2e3f",
  "episode_id": "episode.example",
  "profile": "default",
  "model": "small",
  "force": false,
  "skip": ["probe", "clean"],
  "status": "queued",
  "error": null,
  "created_at": 1788624000.12,
  "started_at": null,
  "finished_at": null,
  "log_path": null,
  "event_count": 0
}
```

#### Error Responses
- `404 Not Found`: Episode not found.
- `422 Unprocessable Entity`: Unknown skip stages or invalid model size.

---

### `GET /api/episodes/{id}/deliverables`

Lists every finished output for an episode, each as a `/api/media/...` URL (or `null` if that output
does not exist yet).

#### Response (200 OK)

```json
{
  "final_mp3": "/api/media/episode.example/ep03/ep03.mp3",
  "chapters_json": "/api/media/episode.example/ep03/chapters.json",
  "receipt": "/api/media/episode.example/ep03/receipt.json",
  "parts": [
    {
      "part": "example-part-1",
      "edited_wav": "/api/media/episode.example/parts/example-part-1/example-part-1.edited.wav",
      "clips": [
        {
          "mp3": "/api/media/episode.example/parts/example-part-1/clips/1.mp3",
          "srt": "/api/media/episode.example/parts/example-part-1/clips/1.srt"
        }
      ]
    }
  ]
}
```

#### Error Responses
- `404 Not Found`: Episode not found.
- `422 Unprocessable Entity`: Manifest invalid.

---

## Jobs & Real-time Progress

### `GET /api/jobs/{id}`

Returns the status and metadata for job `{id}`.

#### Response (200 OK)

```json
{
  "id": "4a7b9c1d2e3f",
  "episode_id": "episode.example",
  "profile": "default",
  "model": "small",
  "force": false,
  "skip": [],
  "status": "running",
  "error": null,
  "created_at": 1788624000.12,
  "started_at": 1788624000.15,
  "finished_at": null,
  "log_path": "out\\episode.example\\dashboard-job-4a7b9c1d2e3f.log",
  "event_count": 14
}
```

#### Job Statuses
- `queued`: Waiting for previous job to finish.
- `running`: Currently executing.
- `done`: Completed successfully.
- `failed`: Failed with error (see `error` field).
- `cancelled`: Aborted by user cancel request.

---

### `GET /api/jobs/{id}/events`

Streams real-time Server-Sent Events (SSE) for the job until it reaches a terminal status (`done`, `failed`, or `cancelled`).
Content type: `text/event-stream`.

Each SSE message has the format:
```
id: <seq>
event: <event_type>
data: <json_payload>
```

#### Event Types
- `job_started`
- `started` (stage started)
- `finished` (stage finished with elapsed duration)
- `cached` (stage hit cache)
- `skipped` (stage skipped)
- `log` (captured stdout/stderr line)
- `job_finished`
- `job_failed`
- `job_cancelled`

#### SSE Data Payload Example

```json
{
  "seq": 3,
  "event": "started",
  "stage": "transcribe",
  "part": "example-part-1",
  "elapsed": 0.0,
  "message": "",
  "ts": 1788624002.45
}
```

```json
{
  "seq": 4,
  "event": "finished",
  "stage": "transcribe",
  "part": "example-part-1",
  "elapsed": 2.14,
  "message": "",
  "ts": 1788624004.59
}
```

```json
{
  "seq": 5,
  "event": "log",
  "stage": null,
  "part": null,
  "elapsed": 0.0,
  "message": "[transcribe] Transcribing example-part-1 (small)...",
  "ts": 1788624002.50
}
```

---

### `POST /api/jobs/{id}/cancel`

Signals job `{id}` to cancel. If the job is currently running, cancellation is evaluated before the start of the next stage. If queued, it is marked cancelled immediately.

#### Response (200 OK)

```json
{
  "id": "4a7b9c1d2e3f",
  "episode_id": "episode.example",
  "profile": "default",
  "model": "small",
  "force": false,
  "skip": [],
  "status": "cancelled",
  "error": null,
  "created_at": 1788624000.12,
  "started_at": 1788624000.15,
  "finished_at": 1788624005.10,
  "log_path": "out\\episode.example\\dashboard-job-4a7b9c1d2e3f.log",
  "event_count": 8
}
```

#### Error Responses
- `404 Not Found`: Job `{id}` not found.

---

## Part Plans & Transcripts

### `GET /api/episodes/{id}/parts/{part}/plan`

Returns the `plan.json` for a given part under `out/{id}/parts/{part}/plan.json`.

#### Response (200 OK)

```json
{
  "version": 1,
  "source_duration": 40.5,
  "items": [
    {
      "id": "keep-0",
      "kind": "keep",
      "start": 0.0,
      "end": 5.2,
      "reason": "speech",
      "enabled": true
    },
    {
      "id": "pause-1",
      "kind": "cut",
      "start": 5.2,
      "end": 7.0,
      "reason": "pause",
      "enabled": true
    },
    {
      "id": "filler-2",
      "kind": "cut",
      "start": 12.3,
      "end": 12.8,
      "reason": "filler:那個",
      "enabled": false
    }
  ]
}
```

#### Error Responses
- `404 Not Found`: Episode, part, or `plan.json` not found.

---

### `PUT /api/episodes/{id}/parts/{part}/plan`

Updates the `enabled` flags for items in `plan.json`. Validates the updated plan with `audit_mod.audit_plan` against `{part}.clean.wav`.
The file is saved **only** if the audit passes. If the audit fails, the original `plan.json` is left unmodified and status code 422 is returned.

#### Request Body

```json
[
  {
    "id": "filler-2",
    "enabled": true
  }
]
```

#### Response (200 OK - Audit Passed)

```json
{
  "ok": true,
  "seconds_removed": 2.3,
  "coverage_ratio": 1.0
}
```

#### Error Responses (422 Unprocessable Entity - Audit Failed)

```json
{
  "ok": false,
  "errors": [
    "item filler-99 overlaps with keep-0 [0.00s - 5.20s]"
  ]
}
```

---

### `POST /api/episodes/{id}/parts/{part}/plan/cuts`

Adds a human-drawn cut to `plan.json` -- the only way to remove audio the automatic pause/filler detectors did not
flag (an off-topic tangent, a mistake to redo). Any existing `keep` item the new range overlaps is trimmed or split
so the plan stays a non-overlapping partition; an existing `cut`/`fade` item in the way is left alone and reported
as a conflict. Validated with the same `audit_mod.audit_plan` gate as `PUT .../plan`, and saved only if it passes.

#### Request Body

```json
{ "start": 12.4, "end": 18.9, "reason": "off-topic tangent" }
```

`reason` is optional (defaults to `"manual"`).

#### Response (200 OK)

```json
{ "ok": true, "id": "manual-0001", "seconds_removed": 8.6, "coverage_ratio": 0.98 }
```

#### Error Responses
- `404 Not Found`: `plan.json` or the part's clean audio not found.
- `422 Unprocessable Entity`: `end <= start`, or the audit rejected the result (`{"ok": false, "errors": [...]}`).

---

### `POST /api/episodes/{id}/parts/{part}/plan/ai-suggest`

Asks a locally installed AI CLI (configured via `ai_suggest.command` in the profile, e.g. `["claude", "-p"]`) to
review the part's transcript and propose additional cuts -- redundant retakes, off-topic tangents -- the same
categories a human would look for manually. Every candidate is validated with `audit_mod.audit_plan` against the
*current* `plan.json` and returned for review; **nothing is written to disk by this endpoint**. Accept a suggestion
by calling `POST .../plan/cuts` with its `start`/`end`/`reason`.

#### Request Body

```json
{ "profile": "default" }
```

#### Response (200 OK)

```json
{
  "ok": true,
  "suggestions": [
    { "start": 42.0, "end": 47.5, "reason": "redundant retake of the intro", "valid": true, "errors": [] },
    { "start": 90.0, "end": 95.0, "reason": "off-topic tangent", "valid": false, "errors": ["item ... overlaps with keep-0"] }
  ]
}
```

#### Error Responses
- `400 Bad Request`: `ai_suggest.command` is not set for the resolved profile.
- `404 Not Found`: `plan.json`, `transcript.json`, or the part's clean audio not found.
- `502 Bad Gateway`: the configured CLI was not found, timed out, exited non-zero, or did not reply with a JSON array.

---

### `GET /api/episodes/{id}/parts/{part}/transcript`

Returns the `transcript.json` for the given part under `out/{id}/parts/{part}/transcript.json`.

#### Response (200 OK)

```json
{
  "language": "zh",
  "duration": 40.5,
  "segments": [
    {
      "id": 0,
      "start": 0.0,
      "end": 3.4,
      "text": "歡迎收聽今天的節目。",
      "words": [
        { "word": "歡迎", "start": 0.0, "end": 0.6, "probability": 0.98 },
        { "word": "收聽", "start": 0.6, "end": 1.2, "probability": 0.99 }
      ]
    }
  ]
}
```

#### Error Responses
- `404 Not Found`: Transcript not found.

---

### `GET /api/episodes/{id}/parts/{part}/peaks`

Min/max waveform samples for the part, bucketed for a scrollable/zoomable waveform view. Decodes
`{part}.clean.wav` (or, before the pipeline has run, the original source file) to raw mono `s16le`
PCM via ffmpeg and reduces it to exactly `buckets` `[min, max]` pairs with numpy.

Cached to `out/{id}/parts/{part}/peaks.<buckets>.json`, keyed on the decoded wav's sha256; a repeat
request with the same `buckets` and an unchanged wav is served straight from that cache file (it is
not rewritten).

#### Query Parameters
- `buckets` *(integer, optional, default: 2000)*: number of `[min, max]` pairs to return.

#### Response (200 OK)

```json
{
  "wav_sha256": "9f2c...",
  "buckets": 2000,
  "peaks": [[-120, 118], [-340, 355], "... exactly `buckets` entries ..."]
}
```

#### Error Responses
- `404 Not Found`: Episode/part not found, or no clean or source audio exists yet for the part.
- `422 Unprocessable Entity`: `buckets` is not a positive integer.

---

## Clips

### `GET /api/episodes/{id}/parts/{part}/clips`

Returns `clips.json` (candidate clip windows scored for social cuts) if it has been generated for
this part, under `out/{id}/parts/{part}/clips.json`.

#### Response (200 OK)

See `clips.json`'s schema (`podcast-autopilot.clips/v1`): `source`, `transcript`, `profile.keywords`,
and `candidates[]` (each with `id`, `start`, `end`, `text`, `score`, `score_components`, optional `rerank`).

#### Error Responses
- `404 Not Found`: `clips.json` not found; run clips first.

---

### `POST /api/episodes/{id}/parts/{part}/clips`

Enqueues a background job (on the same job queue/SSE stream as `POST /api/episodes/{id}/run`) that
scores clip candidates from the part's transcript (`transcribe_mod` + `clips_mod.build_candidates` /
`rerank_with_llm`) and writes `out/{id}/parts/{part}/clips.json`. Requires `transcript.json` to
already exist (run the pipeline through the `transcribe` stage first); it does **not** require the
part's clean audio, so candidates can be generated as soon as a transcript exists.

The job resolves audio the same way `GET .../peaks` does (`{part}.clean.wav`, falling back to the
original source file before the pipeline reaches the `clean` stage) to record `source.sha256`/
`source.duration` in `clips.json` when available; if neither exists yet, those fields are `null`.

#### Request Body

```json
{ "render": false }
```

- `render` *(boolean, optional, default: false)*: also cut each candidate to
  `out/{id}/parts/{part}/clips/<n>.mp3` + `.srt`. Rendering does require audio (clean or source) to
  cut from; the job fails if none is found.

#### Response (200 OK)

Same job shape as `POST /api/episodes/{id}/run` (see [Jobs & Real-time Progress](#jobs--real-time-progress)),
with `kind: "clips"` and `part_id` set. Progress is reported via `GET /api/jobs/{id}/events` with
stages `"clips"` and (when `render` is true) `"render"`.

#### Error Responses
- `404 Not Found`: episode/part not found, or `transcript.json` does not exist yet.

---

### `DELETE /api/episodes/{id}/parts/{part}/clips`

Deletes the part's generated `clips.json` and all rendered clip files under its `clips/` directory.
The operation is idempotent and returns `{ "ok": true }`; it returns `409 Conflict` if clip generation
for this part is still queued or running.

---

## Media Serving

### `GET /api/media/{episode}/{path:path}`

Serves audio and data files from `out/{episode}/` or `media/{episode}/`.
- Rejects path traversal attempts (e.g. containing `..` or escaping directory).
- Supports HTTP Range requests (`Range: bytes=start-end`), returning `206 Partial Content` with `Accept-Ranges: bytes` so browsers can seek playback in `<audio>` / `<video>`.

#### Example Request with Range Header

```http
GET /api/media/episode.example/parts/example-part-1/example-part-1.clean.wav HTTP/1.1
Host: localhost:8765
Range: bytes=0-99
```

#### Response (206 Partial Content)

```http
HTTP/1.1 206 Partial Content
Accept-Ranges: bytes
Content-Range: bytes 0-99/1411244
Content-Length: 100
Content-Type: audio/x-wav

[100 binary bytes]
```

#### Error Responses
- `404 Not Found`: File does not exist or path escapes allowed directories.

---

## SPA Static Serving

When the built frontend exists at `web/dist`:
- Any GET request not matching `/api/*` serves the matching static file from `web/dist`.
- If the requested path is not a file, it falls back to `web/dist/index.html` (supporting client-side routing).
- Unmatched requests under `/api/*` always return a JSON `404 Not Found` response instead of HTML.
