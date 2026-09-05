# Changelog

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
- `docs/RUNS.md`: timings and results of the real EP3 end-to-end run.
- `run.ps1`: one-command runner (creates `.venv`, installs dependencies,
  checks ffmpeg, runs the pipeline).
- `app.py`: Streamlit control panel (run, view `RUN_REPORT.md`, review/
  toggle plan items, re-apply).
- README (zh-TW + English), profile examples, edit-plan JSON schema
  `podcast-autopilot.edit-plan/v1`.
