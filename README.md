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

## Edit-plan 合約

Schema id：`podcast-autopilot.edit-plan/v1`。結構：

```
{schema, created, source: {path, sha256, duration, sr, channels},
 profile: {name, sha256}, items: [{id, kind, start, end, reason, enabled}],
 render: {crossfade_ms, sample_rate, loudness_target_i, loudness_target_tp}}
```

目前支援的 `kind`：`keep` | `cut` | `fade`（之後的任務會加入 filler /
denoise / chapter / clip，不需要改這個 schema，因為 `kind` 只是字串，
真正把關「哪些 kind 合法」的是 `audit.py`）。

`audit.py` 的 fail-closed 規則：來源檔案 sha256 必須與計畫記錄的一致、
項目不重疊、都在 `[0, duration]` 範圍內、未知的 kind 一律拒絕。任何一項
失敗，整份計畫視為不可用（不會回傳部分結果）。

輸出：`out/<檔名>/<檔名>.edited.wav`，以及同目錄下的 `receipt.json`
（來源/計畫/輸出三者的 sha256、ffmpeg 版本、渲染後量測到的響度）。

## 響度目標

-16 LUFS 整合響度 / -1.5 dBTP 真峰值（mono），對應 `render` 設定裡的
`loudness_target_i` / `loudness_target_tp`。

## 測試

```powershell
.venv\Scripts\pytest
```

涵蓋 audit 的拒絕案例（重疊、超出範圍、hash 不符、未知 kind）以及完整
selftest 流程。

---

## English (short)

CPU-only podcast post-production CLI for Windows. `probe` (ffprobe +
loudnorm measure) -> `plan` (edit-plan JSON, schema
`podcast-autopilot.edit-plan/v1`) -> `audit` (fail-closed: hash match, no
overlaps, in-range, known kinds only) -> `apply` (ffmpeg renders `keep`
segments with a short acrossfade at each join) -> `receipt` (sha256 of
source/plan/output + ffmpeg version + post-render loudness).

Setup: `python -m venv .venv && .venv\Scripts\pip install -r
requirements.txt && .venv\Scripts\pip install -e . && .venv\Scripts\python
-m podcast_autopilot selftest`. ffmpeg/ffprobe resolve in order:
`config.ffmpeg_path` > `PATH` > `tools/ffmpeg/bin` (gitignored); install
with `winget install Gyan.FFmpeg` or drop the binaries into
`tools/ffmpeg/bin` manually.

Architectural reference: Hao0321/video-autopilot-kit (see `NOTICE`).
License: MIT.
