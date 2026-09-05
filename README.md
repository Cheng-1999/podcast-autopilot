# podcast-autopilot

CPU-only 的 Podcast 後製自動化工具（Windows，無需 GPU）。核心流程是
`probe`（量測）→ `plan`（剪輯計畫）→ `audit`（fail-closed 驗證）→ `apply`
（用 ffmpeg 渲染）→ `receipt`（產出可追溯的收據）。

## 環境需求

- Windows、Python 3.12、CPU only
- ffmpeg / ffprobe：本專案不內建，安裝順序為
  `設定檔 ffmpeg_path` > `PATH` > `tools/ffmpeg/bin`（此路徑已加入
  `.gitignore`，不會被提交）
  - 建議：`winget install Gyan.FFmpeg`
  - 若 winget 失敗，改為手動下載 gyan.dev 的 release zip，把
    `ffmpeg.exe` / `ffprobe.exe` 放進 `tools/ffmpeg/bin/`
  - 兩個路徑都找不到時，程式會直接報錯並提示如何安裝（fail closed）

## 安裝（5 個指令內）

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install -e .
.venv\Scripts\python -m podcast_autopilot selftest
.venv\Scripts\python -m podcast_autopilot probe "路徑\到\你的錄音.wav"
```

## 指令

- `python -m podcast_autopilot probe <audio>`：印出 ffprobe 資訊（codec、
  取樣率、聲道數、sample format、長度）以及整體響度（LUFS，透過 ffmpeg
  loudnorm 量測模式）。同時支援 32-bit float WAV 與 mp3。
- `python -m podcast_autopilot selftest`：產生一段 30 秒的合成音檔
  （純音 + 白噪音），跑過完整的 probe → plan（identity keep）→ audit →
  apply → receipt 流程，並確認輸出長度與輸入誤差在 50ms 以內。
- `python -m podcast_autopilot transcribe <audio> [--model small|medium]`：
  用 faster-whisper（CTranslate2、CPU、int8）轉錄成繁體中文，輸出到
  `out/<檔名>/`：`transcript.json`（segments + 逐字 words，含
  start/end/probability）、`transcript.srt`、`transcript.md`（每個
  segment 一段，開頭是 `[mm:ss]` 時間戳）。模型預設 `small`，可用
  `--model medium` 或設定檔 `whisper_model_size` 切換；模型檔快取在
  `tools/models/`（已加入 `.gitignore`，不會被提交，首次執行會從
  Hugging Face 下載）。Whisper 對 `language="zh"` 常常偏向簡體輸出，
  所以轉錄結果會再跑一次 `opencc s2twp` 轉換成繁體，並記錄實際改了幾個
  字（`opencc_chars_changed`）。
- `python -m podcast_autopilot plan-fillers <audio> [--model small|medium]`：
  在 `out/<檔名>/transcript.json` 已存在時直接重用（否則先轉錄一次），
  偵測語助詞（預設 `嗯`、`呃`、`啊`、`那個`、`就是說`、`然後`，可在設定檔
  `filler_words` 覆寫），只有「該詞前後都有大於 `filler_pause_threshold_s`
  秒的停頓（預設 0.2s）且辨識機率 `probability` 大於
  `filler_min_probability`（預設 0.5）」才算數；轉錄的第一個與最後一個
  word 因為單邊沒有鄰居、無法確認停頓，一律不提案（fail closed）。
  偵測到的候選會以 `kind: "filler"`、`enabled: false` 的形式寫進
  `out/<檔名>/plan.json`（純提案，不會改變輸出，除非人工把 `enabled` 改成
  `true`）。重複執行是冪等的：區間相同的既有 filler 項目原樣保留（含人工
  改成 `enabled: true` 的），不再被偵測到的停用提案會被移除、已啟用的
  人工決定則保留，新候選補在最後一個編號之後，不會累積出重疊的重複提案。多字語助詞
  （如「那個」「然後」）能否被抓到，取決於 faster-whisper 對中文字詞邊界
  的切法，不保證每次都切成一個 word。
- `python -m podcast_autopilot clean <audio> [--profile default|spotify]`：依序執行
  denoise、highpass、de-ess、compression 與 two-pass loudnorm，輸出
  `out/<檔名>/<檔名>.clean.wav` 和含 engine/filtergraph/量測結果的 receipt。
  `denoise.engine` 支援 `auto`、`noisereduce`、`afftdn`、`off`；auto 在
  `noisereduce` 不可用時會記錄警告並使用 `afftdn=nr=12:nf=-25`。

## Edit-plan 合約

Schema id：`podcast-autopilot.edit-plan/v1`。結構：

```
{schema, created, source: {path, sha256, duration, sr, channels},
 profile: {name, sha256}, items: [{id, kind, start, end, reason, enabled}],
 render: {crossfade_ms, sample_rate, loudness_target_i, loudness_target_tp}}
```

目前支援的 `kind`：`keep` | `cut` | `fade` | `filler`（之後的任務會加入
denoise / chapter / clip，不需要改這個 schema，因為 `kind` 只是字串，
真正把關「哪些 kind 合法」的是 `audit.py`）。`keep`/`cut`/`fade` 這三種是
「切分」型：彼此不能重疊、必須按 start 排序。`filler` 不一樣，它是巢狀在
某個 `keep` 項目裡的提案標記（見上面 `plan-fillers`），本來就該與該
`keep` 重疊，`audit.py` 對它的規則是另外一套：`filler` 之間不能互相重疊、
且每個 `filler` 的範圍必須完全落在某個 `keep` 項目內；若計畫只有 `cut`
（`plan-pauses` 的輸出），則以 `cut` 的補集當作 keep 範圍（與 `apply.py`
的渲染方式一致，且不論 `cut` 是否啟用都算，避免切換 `enabled` 讓提案失效）。

`audit.py` 的 fail-closed 規則：來源檔案 sha256 必須與計畫記錄的一致、
`keep`/`cut`/`fade` 彼此不重疊、都在 `[0, duration]` 範圍內、未知的 kind
一律拒絕、`filler` 需完全落在某個 `keep` 內且彼此不重疊。任何一項失敗，
整份計畫視為不可用（不會回傳部分結果）。

`apply.py` 只渲染 `enabled=true` 的 `keep` 項目；如果某個 `filler` 項目被
人工改成 `enabled: true`，渲染時會把它從所在的 `keep` 範圍裡挖掉，挖出的
兩段用 15ms 的短 crossfade 接起來（跟一般 keep-keep 之間用
`render.crossfade_ms` 的 crossfade 不是同一個設定）。`enabled=false`（預設）
的 filler 提案完全不影響輸出。因為啟用的 filler 實際上就是一個 cut，
`audit.py` 計算 `max_removed_fraction` 與 `total_cut_duration` 時會把它和
`cut` 項目一起算進去（`total_keep_duration` 相對扣除），不會出現「通過
audit 卻切掉超過上限」的情況。

輸出：`out/<檔名>/<檔名>.edited.wav`，以及同目錄下的 `receipt.json`
（來源/計畫/輸出三者的 sha256、ffmpeg 版本、渲染後量測到的響度）。

## 響度目標

-16 LUFS 整合響度 / -1.5 dBTP 真峰值（mono），對應 `render` 設定裡的
`loudness_target_i` / `loudness_target_tp`。

## 轉錄 CPU 速度（實測）

機器：本專案開發機（Windows，CPU only，faster-whisper `small`、
`compute_type=int8`）。測試素材：`EP3-1.wav` 前 5 分鐘（300 秒，
44.1kHz mono 32-bit float wav）。

結果：135.7 秒轉錄完 300 秒音檔，約 **2.2x 即時速度**（即時長度的
45% 耗時）。換算下來，一集 60 分鐘的 podcast 大約需要 27 分鐘 CPU 時間。

## 測試

```powershell
.venv\Scripts\pytest
```

涵蓋 audit 的拒絕案例（重疊、超出範圍、hash 不符、未知 kind、filler 未落在
keep 內、filler 互相重疊）、filler 偵測的單元測試（人造 word 清單）、
一個轉錄 30 秒合成音檔（無語音，純音+白噪音）的 smoke test，以及完整
selftest 流程。

---

## English (short)

CPU-only podcast post-production CLI for Windows. `probe` (ffprobe +
loudnorm measure) -> `plan` (edit-plan JSON, schema
`podcast-autopilot.edit-plan/v1`) -> `audit` (fail-closed: hash match, no
overlaps, in-range, known kinds only) -> `apply` (ffmpeg renders `keep`
segments with a short acrossfade at each join) -> `receipt` (sha256 of
source/plan/output + ffmpeg version + post-render loudness).

`transcribe <audio> [--model small|medium]` runs faster-whisper
(CTranslate2, CPU, `compute_type=int8`, model cached under `tools/models/`,
gitignored) with `language="zh"`, `word_timestamps=True`, `vad_filter=True`.
Output leans Simplified even with `language="zh"`, so every segment/word is
re-run through `opencc s2twp`; the number of characters that pass changed is
logged as `opencc_chars_changed`. Writes `out/<stem>/transcript.{json,srt,md}`
(the `.md` has one `[mm:ss]`-prefixed paragraph per segment).

`plan-fillers <audio> [--model small|medium]` reuses `transcript.json` if
present, flags filler words (`filler_words` in config, default 嗯/呃/啊/那個/
就是說/然後) that are isolated by a pause > `filler_pause_threshold_s` (0.2s)
on both sides with `probability > filler_min_probability` (0.5), and writes
them into `out/<stem>/plan.json` as `kind: "filler"`, `enabled: false`
(idempotent: re-running replaces stale disabled proposals instead of
appending duplicates; matching and human-enabled items are kept; first/last
words are never proposed since one-sided pauses cannot be confirmed)
proposals — no effect on the render until a human flips `enabled` to `true`.
`audit.py` requires every `filler` item to sit fully inside a `keep` item (or,
for a cut-only pause plan, inside the complement of the `cut` items) and
not overlap other `filler` items (a different rule than the `keep`/`cut`/`fade`
no-overlap partition check). `apply.py` carves an enabled `filler` item out of
its enclosing `keep` item at render time, joining the two remaining pieces
with a 15ms crossfade instead of the plan's configured one.

Setup: `python -m venv .venv && .venv\Scripts\pip install -r
requirements.txt && .venv\Scripts\pip install -e . && .venv\Scripts\python
-m podcast_autopilot selftest`. ffmpeg/ffprobe resolve in order:
`config.ffmpeg_path` > `PATH` > `tools/ffmpeg/bin` (gitignored); install
with `winget install Gyan.FFmpeg` or drop the binaries into
`tools/ffmpeg/bin` manually.

Architectural reference: Hao0321/video-autopilot-kit (see `NOTICE`).
License: MIT.
