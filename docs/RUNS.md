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

## Fresh-clone smoke run (bundled example)

`git clone` into a temp dir, then `.\run.ps1 examples\episode.example.yaml`
(creates `.venv`, installs requirements, checks ffmpeg, generates the two
20 s placeholder parts, runs the pipeline): `RUN OK`, 229 s wall including
the pip install and the first whisper model download, MP3 of 40.5 s at
-16.4 LUFS / -3.9 dBTP, `RUN_REPORT.md` written.
