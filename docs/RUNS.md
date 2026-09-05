# Real end-to-end runs

Timings and results of `python -m podcast_autopilot run` on real material.
No audio is committed; the manifest used here (`examples/ep3.local.yaml`) is
gitignored because it points at recordings outside the repo.

## EP3 (2026-09-05, T-0008-P7-F1)

Machine: the development laptop (Windows 11, CPU only, no GPU), Python 3.12,
ffmpeg 9.0.1 (gyan.dev full build), faster-whisper `small` (CTranslate2 int8).
Command (the same command re-applies after a `plan.json` edit; unchanged
stages are cache hits):

```
python -m podcast_autopilot run "examples\ep3.local.yaml" --profile default --model small --out-dir "out" --config "profiles\default.example.yaml"
```

Input: two raw takes kept outside the repo (see the gitignored manifest), 32-bit float
mono 44.1 kHz, no intro/outro/BGM, one chapter marker.

| Part | Duration | Loudness before clean | Loudness after clean | Pause cuts | Filler proposals (disabled) | Seconds removed |
|---|---|---|---|---|---|---|
| EP3-1.wav | 1225.0 s | -34.6 LUFS / -0.0 dBTP | -16.5 LUFS / -2.1 dBTP | 7 | 2 (`然後`) | 7.99 s |
| EP3-2.wav | 1217.1 s | -36.9 LUFS / -7.0 dBTP | -16.5 LUFS / -2.0 dBTP | 7 | 0 | 7.32 s |

Per-stage wall time (seconds, from `out/ep3.local/RUN_REPORT.md`):

| Stage | EP3-1 | EP3-2 |
|---|---|---|
| probe | 16.4 | 15.4 |
| clean | 126.4 | 96.8 |
| plan-pauses | 21.5 | 14.2 |
| transcribe | 713.8 | 477.6 |
| plan-fillers | 0.2 | 0.2 |
| audit | 0.2 | 0.2 |
| apply | 15.9 | 15.3 |
| assemble (both parts, MP3 export) | 292.7 | |

- Whole run: 1811 s wall (about 30 min for 40.7 min of audio, 0.74x real time).
  Transcription is 66% of it (1.7x real time on EP3-1, 2.5x on EP3-2); the
  rest is dominated by the three full-file ffmpeg passes in `clean` and the
  loudness measurement / MP3 encode in `assemble`.
- Output: `out/ep3.local/ep03/ep03.mp3`, 2427.0 s, mono 44.1 kHz 96 kbps,
  -17.5 LUFS / -1.6 dBTP, chapters in `chapters.{json,txt,ffmetadata}`,
  receipt with input/output sha256 in `receipt.json`.
- Second invocation with `--dry-run` right after: every stage of both parts
  and `assemble` reported `cached`, 2 s wall.
- A first attempt of this run (before the fixes in T-0008-P7-F1) found zero
  pauses in either part: the absolute `pauses.noise: "-35dB"` threshold never
  triggers on -16 LUFS cleaned audio. With the loudness-relative default
  (`"0LU"`) each part yields 7 cuts of 1.5-2.3 s pauses tightened to 0.6 s.

### Quality note (what a human still has to check)

- **Better**: both takes now sit at a consistent -16.5 LUFS with a -2 dBTP
  ceiling instead of -35/-37 LUFS raw with an EP3-1 peak at 0 dBFS, the
  noise floor is reduced, the two parts join at matched level, and 14
  over-long pauses are tightened without audible clicks (20 ms crossfades).
- **Final MP3 is 1.5 LU under target** (-17.5 LUFS vs -16.0): the assembled
  file's true-peak limiter at -1.5 dBTP takes the level down after the join.
  Acceptable for most hosts (Apple/Spotify normalise anyway) but worth a
  listen; raise `loudness_target_i` in the profile or re-check `assemble`'s
  final gain if a hotter master is wanted.
- **Filler proposals are conservative**: only two `然後` on EP3-1 and none on
  EP3-2 (probability >= 0.5, pause >= 0.2 s on both sides). They are written
  disabled; enable them in `plan.json` (or the Streamlit app) and re-run the
  command above.
- **EP3-1 transcript needs proof-reading**: 861 of 1087 segments carry a
  trailing full-width `１` (a known small-model hallucination that
  self-reinforces once it starts; EP3-2 has 0 of 984). Timestamps and the
  filler detection are unaffected, but the `.srt`/`.md` are not publishable
  as-is. The first seconds of EP3-2 are garbled English tokens (`hasn he`,
  `public TCP`) where the speaker starts mid-sentence. A `medium` model run or
  a text post-pass is the follow-up (see the board handoff from T-0008-P7-F1).
- **Chapters**: the manifest only declares one chapter; real chapter times
  for the assembled timeline must be entered by hand after listening.

## EP3 via the dashboard (2026-09-06, T-0009-P6)

Same source recordings as the CLI run above
(`C:\Users\a8878\OneDrive\桌面\podcast\EP3-1.wav` / `EP3-2.wav`), registered
by path (not copied) as a new episode through `.\dashboard.ps1`'s
new-episode form. A fresh episode id (`ep3-dashboard-run-ep03`) was used, so
the `out/ep3.local` cache from the CLI run did not apply, as expected;
every stage re-ran from scratch.

- **Full run**: `POST /api/episodes/{id}/run`, watched via the live SSE
  stage grid. The run's wall-clock spans several supervisor restarts (this
  task was interrupted three times by `error_max_turns` before its budget
  was raised — see the board history), so the raw elapsed time between
  "clean done" for EP3-1 (05:04) and the first assembled `ep03.mp3` (06:13)
  is not a clean perf number. The useful observation is qualitative: the
  per-stage cache (`stage_cache.json`) meant each restart resumed at the
  next un-cached stage instead of re-transcribing from the top — the same
  caching that makes "Reapply" cheap also made the dashboard resilient to
  the process being killed and restarted mid-run.
- **Review**: opened both parts' plan/waveform. EP3-1 proposed one disabled
  filler (`filler-0001`, `然後` p=0.88); EP3-2 proposed one disabled filler
  (`filler-0001`, `然後` p=0.54). Left EP3-1's as-is, enabled EP3-2's via
  `PUT /api/episodes/{id}/parts/EP3-2/plan` (200 OK, re-audited
  `seconds_removed` 7.32s -> matches the applied edit).
- **Reapply**: `POST /api/episodes/{id}/run` again with the same body
  (`force: false`). Caching worked as designed — `probe` / `clean` /
  `plan-pauses` / `transcribe` / `plan-fillers` stayed `cached` for both
  parts, EP3-1's `audit` / `apply` stayed `cached` (its plan did not
  change), and only EP3-2's `audit` (0.19s) and `apply` (15.80s) re-ran,
  followed by a full `assemble` (378.89s, both parts are joined into one
  file so any plan change forces a re-encode) - 397s wall for the whole
  reapply job, per `RUN_REPORT.md`'s stage table.
- **Deliverables**: `GET /api/episodes/{id}/deliverables` lists `ep03.mp3`;
  verified it plays by decoding it with `ffprobe` rather than a manual
  listen through the UI (this task ran headless) - 2426.8s (~40.4 min),
  96 kbps mono, -17.4 LUFS / -1.6 dBTP, ID3 tags (`title`/`artist`/`album`/
  `comment`) correctly populated from the episode manifest's `tags`.
- Quality observations carry over from the CLI run above: filler proposals
  are still conservative (one per part, both borderline probability), and
  EP3-1's transcript still needs proof-reading before publishing (see the
  CLI run's note on the `１` hallucination — not re-checked here since the
  transcript stage was cached and unchanged from that run).

## Fresh-clone smoke run (bundled example)

`git clone` into a temp dir, then `.\run.ps1 examples\episode.example.yaml`
(creates `.venv`, installs requirements, checks ffmpeg, generates the two
20 s placeholder parts, runs the pipeline): `RUN OK`, 229 s wall including
the pip install and the first whisper model download, MP3 of 40.5 s at
-16.4 LUFS / -3.9 dBTP, `RUN_REPORT.md` written.

## Fresh-clone dashboard smoke run (2026-09-06, T-0009-P6-F1)

`git clone` the `feat/dashboard` branch into a fresh temp directory, then
`.\dashboard.ps1 -Port 18766 -NoBrowser` (a non-default port: this machine's
8765 is already bound by the agentboard supervisor's own dashboard, see the
board ledger) with no pre-existing `.venv`, `web/dist`, or `out/` in the
clone:

- `.venv` created and dependencies installed: clone+venv-create at
  06:33:12->06:33:53, then `pip install -r requirements.txt` + `pip install
  -e .` finished by the time `web/`'s `npm ci && npm run build` completed at
  06:38:10 (~4m17s for pip+npm together) - `✓ built in 4.45s` for the Vite
  build itself.
- `make-example` generated the two placeholder parts, uvicorn came up on
  `http://0.0.0.0:18766` immediately after - about 5 minutes wall from clone
  to a serving dashboard.
- `GET /api/health` returned `ffmpeg_ok: true` and the resolved ffmpeg/
  ffprobe paths; `GET /api/episodes` listed the bundled `episode.example`
  manifest.
- Ran the bundled example the same way the UI would (`POST
  /api/episodes/episode.example/run` with `model: small`), headless since
  this check has no browser: no stage cache existed yet in the fresh clone's
  `out/`, so `small` was downloaded from the HF Hub on first use (unauthenticated,
  rate-limit warning only, no failure) and `transcribe` actually ran instead
  of hitting cache (47.95 s on `example-part-1`, its only non-trivial stage;
  every other stage on both parts finished in low single-digit seconds).
  Status reached `"done"`, `assembly.status: "ran (4.53s)"`.
- Deliverable: `ep03.mp3`, confirmed by decoding with `ffprobe` (this check
  ran headless): 40.5 s, 96 kbps, matches the API's reported -16.4 LUFS /
  -3.6 dBTP. `GET /api/episodes/episode.example/deliverables` listed it plus
  both parts' edited wavs.
- Temp clone and its venv/`out/`/`web/dist` were deleted after the check;
  nothing from it is committed.

## Design gate (2026-09-06, T-0009-P6-F1)

Ran against the dashboard's own dev server (`npm run dev`, proxying `/api`
to a local backend instance) rather than the built SPA, so `impeccable
detect`'s Puppeteer pass sees fully client-rendered routes:

- `npx impeccable detect http://localhost:5173` (desktop, default
  1280x800 viewport): `[]`, 0 findings.
- `npx impeccable detect --viewport 375x844 http://localhost:5173`
  (mobile width): `[]`, 0 findings.
- `npx impeccable detect src/` (static regex pass over the TSX/CSS source):
  `[]`, 0 findings.
- Taste-library self-check (`00-GUARDRAILS.md`), the three desk-dense
  decisions this build is built on (see `TASTE-LIBRARY.md` and
  `library/desk-dense/entry.md`):
  1. Panel grid with tables as the primary element and sticky headers, no
     hero/cards/illustrations - episodes list, review screen and clips
     table are all dense tables, not card grids.
  2. Tabular monospace numerals for every number that changes (loudness,
     durations, stage timings) via IBM Plex Mono, aligned on the decimal.
  3. Color used only for meaning - the semantic status dots/borders (queued/
     running/done/failed) are the only saturated color in the UI; everything
     else is charcoal/white/muted-label per the family's palette.
  Hero screenshot already on file at
  `C:\Users\a8878\OneDrive\桌面\Style\library\desk-dense\podcast-autopilot-dashboard.png`
  with its note in that folder's `entry.md`.
