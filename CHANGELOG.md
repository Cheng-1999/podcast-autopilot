# Changelog

## 0.2.0

Web dashboard: a FastAPI backend (`src/podcast_autopilot/server/`, all
routes under `/api`) plus a Vite + React 19 + TypeScript SPA (`web/`),
served together by `dashboard.ps1` and recommended over the Streamlit app
for day-to-day use.

- `dashboard.ps1`: one-command runner — creates/updates `.venv`, installs
  Python dependencies, checks ffmpeg/ffprobe, builds `web/` with
  `npm ci && npm run build` when `web/dist` is stale, then serves the API
  and the built SPA together with uvicorn (`-Port`, `-NoBrowser`). Binds
  `0.0.0.0` (LAN-reachable, no authentication) so other devices on the same
  network can drive a run.
- Backend: episode discovery (`episodes/*.yaml` real + `examples/*.yaml`
  bundled), upload-by-path or multipart upload (registers a path, never
  copies the source file, unless using the multipart upload form), run
  jobs with SSE progress streaming and cooperative cancel (checked between
  pipeline stages, so already-cached stage outputs survive a cancel),
  waveform peaks, plan get/put (re-audits before saving, `422` on failure),
  transcript, clips (list + render), deliverables listing, and range-
  request media serving.
- Frontend: episodes list, a new-episode wizard (upload, reorder parts,
  intro/outro/BGM incl. duck parameters, chapter markers), a live run
  screen (SSE-driven stage progress), a review screen (waveform, plan item
  toggles with inline `422` audit errors, snippet playback, reapply), and a
  clips table with inline playback and download. Desk-dense visual family
  (IBM Plex Sans/Mono + Noto Sans TC), zh-TW UI copy.
- `web/e2e/`: a Playwright smoke test against the bundled synthetic example
  (`npm run e2e`), driving episodes-list -> start run -> wait for done ->
  review -> toggle a plan item -> save -> verify `plan.json` changed.
- `docs/RUNS.md`: a real dashboard-driven EP3 run (create-by-path, run,
  review with one filler enabled, reapply, deliverables playback), recorded
  alongside the existing CLI run and the fresh-clone bundled-example smoke
  run.
- README: dashboard is now the recommended way to use the tool; the
  Streamlit app (`app.py`) remains as a functional subset, documented in a
  single line.

## 0.1.0

Initial release. CPU-only Windows podcast post-production pipeline built
around a `probe -> plan -> audit -> apply -> receipt` architecture
(reference: Hao0321/video-autopilot-kit, see `NOTICE`).

- `probe`: ffprobe metadata + ffmpeg `loudnorm` measurement pass.
- `clean`: denoise (`noisereduce` primary, `afftdn` fallback) + highpass +
  de-esser + compressor voice chain, then level-independent loudness
  normalisation: measured pre-gain to nominal level, linear gain to the
  integrated target, 4x-oversampled look-ahead true-peak limiter, and a
  measured verification pass (ffmpeg `loudnorm` is only used to measure).
- `plan-pauses`: pause-tightening edit-plan proposal. The silence threshold
  `pauses.noise` defaults to `"0LU"`, relative to the file's integrated
  loudness (an absolute `"-35dB"` is still accepted), so the same profile
  finds pauses on a -35 LUFS raw take and on the -16 LUFS cleaned part that
  `run` feeds it.
- `transcribe`: faster-whisper (CTranslate2, CPU, int8) Traditional Chinese
  transcription (`opencc s2twp` post-pass), `transcript.{json,srt,md}`.
  Model downloads set `HF_HUB_DISABLE_SYMLINKS=1` so a fresh clone on a
  Windows machine without Developer Mode does not die with WinError 1314.
  (`huggingface_hub` is left unpinned: 1.30 needs a newer click than the
  typer 0.12.5 / click 8.1.8 pins allow; the env var works on any version.)
- `plan-fillers`: filler-word detection from the transcript, written as
  disabled (`enabled: false`) proposals into `plan.json`.
- `audit`: fail-closed edit-plan validation (source hash, no overlaps,
  in-range, known kinds only, filler containment rules).
- `apply`: ffmpeg render of the audited plan with crossfaded joins.
- `assemble`: multi-part join, optional intro/outro crossfade, sidechain-
  ducked BGM, chapter markers, tagged MP3 export with a receipt.
- `run`: one command chaining `probe -> clean -> plan-pauses -> transcribe
  -> plan-fillers -> audit -> apply` per part, then `assemble`, with
  per-stage caching keyed on (source sha256, profile sha256, stage
  version; `transcribe` also keyed on the whisper model size), `--force`,
  `--dry-run`, `--skip`, and a generated `RUN_REPORT.md` (per-stage timings,
  seconds removed, loudness before and after cleaning per part and of the
  final MP3, disabled filler proposals, fully pinned re-apply command).
  `--dry-run` writes its preview to `RUN_REPORT.dry-run.md` so it never
  overwrites the report of the last real run.
- `docs/RUNS.md`: timings and results of the real EP3 end-to-end run.
- `run.ps1`: one-command runner (creates `.venv`, installs dependencies,
  checks ffmpeg, runs the pipeline). With the bundled
  `examples/episode.example.yaml` it first generates the two 20 s placeholder
  parts (`make-example`); that manifest's chapters fit inside those 40 s.
- `app.py`: Streamlit control panel (run, view `RUN_REPORT.md`, review/
  toggle plan items, re-apply).
- README (zh-TW + English), profile examples, edit-plan JSON schema
  `podcast-autopilot.edit-plan/v1`.
