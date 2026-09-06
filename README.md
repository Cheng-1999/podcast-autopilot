# podcast-autopilot

CPU-only 的 Podcast 後製自動化工具（Windows，無需 GPU）。核心流程是
`probe`（量測）→ `plan`（剪輯計畫）→ `audit`（fail-closed 驗證）→ `apply`
（用 ffmpeg 渲染）→ `receipt`（產出可追溯的收據），一個 episode 的多個
part 全部跑完後再 `assemble` 成一集；`run` 把整條流程串成一個指令（見
下面「一鍵執行」）。這個 plan/audit/apply/receipt 架構參考自
[Hao0321/video-autopilot-kit](https://github.com/Hao0321/video-autopilot-kit)，
沒有複製任何程式碼，細節見 `NOTICE`。

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
  denoise、highpass、de-ess、compression，再做響度正規化（先量測輸入、
  以線性增益推到目標 LUFS，最後用 4 倍超取樣的 look-ahead limiter 壓
  住 true peak；不用 ffmpeg loudnorm 做正規化，因為它遇到 -35 LUFS
  又有 0 dBFS 碰麥聲的家用錄音會退回 dynamic 模式而少 3 dB），輸出
  `out/<檔名>/<檔名>.clean.wav` 和含 engine/filtergraph/量測結果的 receipt。
  `denoise.engine` 支援 `auto`、`noisereduce`、`afftdn`、`off`；auto 在
  `noisereduce` 不可用時會記錄警告並使用 `afftdn=nr=12:nf=-25`。
- `python -m podcast_autopilot assemble <episode.yaml> [--out-dir out]`：把
  `parts`（清乾淨、已剪輯的 part wav）依序接起來，加上可選的 intro/outro
  crossfade、sidechain-ducked 的背景音樂、章節標記，輸出打好 ID3 tag 的
  `out/<episode>/ep<NN>/ep<NN>.mp3` 與 receipt。manifest 結構見
  `examples/episode.example.yaml`。
- `python -m podcast_autopilot clips <audio> [--model small|medium] [--render]`：
  在 `out/<檔名>/transcript.json` 已存在時直接重用（否則先轉錄一次），從逐字稿切出
  5～10 個 30～90 秒的候選片段，見下面「Clips」。
- `python -m podcast_autopilot run <episode.yaml> [--profile default] [--model small|medium] [--skip STAGE ...] [--force] [--dry-run]`：
  一個指令跑完整條後製線，見下面「一鍵執行」。

## 一鍵執行（`run`）

`run` 對 manifest 裡的每個 part 依序執行
`probe -> clean -> plan-pauses -> transcribe -> plan-fillers -> audit -> apply`，
全部 part 都跑完後再 `assemble` 成一集。

```powershell
python -m podcast_autopilot run examples\episode.example.yaml --profile default
```

或直接雙擊 / 執行 `run.ps1`（會自動建立 `.venv`、安裝依賴、檢查
ffmpeg，再呼叫上面的指令）：

```powershell
.\run.ps1 examples\episode.example.yaml
.\run.ps1 examples\episode.example.yaml -Profile spotify -ExtraArgs --dry-run
```

`examples/episode.example.yaml` 指向兩個沒有隨repo提交的佔位音檔
（`example-part-1.wav`／`example-part-2.wav`，因為本專案不提交任何音檔）；
`run.ps1` 偵測到你跑的正是這個內建範例時，會先呼叫
`python -m podcast_autopilot make-example` 產生兩段合成音檔（純音+白噪音），
所以 clone 下來馬上就能跑，不需要準備真的錄音。要跑自己的錄音，複製這個
YAML、把 `parts` 指到你自己的檔案即可。

**快取**：每個 part 在 `out/<episode>/parts/<part>/stage_cache.json`
記錄每個 stage 的來源 sha256、profile sha256 與 stage 版本號（`probe`
也快取，`transcribe` 的 key 額外含 whisper 模型大小，所以 `--model small`
之後改跑 `--model medium` 一定會重新轉錄）；重跑時只要這三者都沒變、且
stage 的輸出檔還在，就直接跳過（狀態顯示為 `cached`）。手動改過 `out/<episode>/parts/<part>/plan.json`（或用下面的
Streamlit 介面勾選/取消 filler 提案）之後重新執行同一個指令，只有
`audit`／`apply` 那個 part 會重跑，`assemble` 則視渲染出來的音檔內容是否
真的變了才決定要不要重跑（見 `RUN_REPORT.md` 底部的重跑指令）；`clean`／
`plan-pauses`／`transcribe`／`plan-fillers` 這些較貴的 stage 完全不受影響
（唯一例外：`plan-pauses` 因版本號或來源改變而重跑時，`plan-fillers` 一定
跟著重跑，因為新的停頓計畫裡沒有先前合併進去的語助詞提案）。
`--force` 會忽略所有快取、全部重跑。`--dry-run` 只印出每個 stage 會是
`ran`／`cached`，不會真的執行任何東西（預覽寫到 `RUN_REPORT.dry-run.md`，
不會蓋掉上一次真正執行的 `RUN_REPORT.md`）。`--skip STAGE` 讓某個 stage 直接
沿用既有輸出檔（若該檔案還不存在會報錯）。

## Clips

`clips` 從 `out/<檔名>/transcript.json`（沒有的話先轉錄一次）切出適合當社群
短片的候選片段，寫到 `out/<檔名>/clips.json`：

```powershell
python -m podcast_autopilot clips "路徑\到\你的錄音.wav"
python -m podcast_autopilot clips "路徑\到\你的錄音.wav" --render
```

- 每個候選片段長度 30～90 秒，起訖點一定落在逐字稿的 segment 邊界上，且該邊界
  前後都要有 >= `clips.pause_threshold_s`（預設 0.4 秒）的停頓，不會從一段話
  中間切開。
- 分數是本地、可解釋的線性組合，每個候選片段連同分數的各項組成一起寫進
  `clips.json`：關鍵字密度（`profile.clips.keywords`，使用者可自行編輯的清單）、
  問句（`？`/`?`）數量、數字出現次數、看起來像專有名詞的詞（大寫開頭的英文字或
  引號／「」『』包起來的片段）、語速是否高於全集中位數，以及語助詞密度的扣分。
- 有設定 `ANTHROPIC_API_KEY` 環境變數時，會額外呼叫 Claude Messages API
  （`claude-opus-5`）重新排序這些候選片段；沒有設定這個環境變數、或呼叫失敗，
  一律直接採用本地分數的排序，指令本身一定會成功。
- 這些候選片段也會以 `kind: "clip"`、`enabled: false` 的形式寫進
  `out/<檔名>/plan.json`（純資訊、不影響 `apply` 的渲染結果；`audit` 已經
  接受 `clip` 這個 kind）。
- `--render` 會把每個候選片段真的切出來，加上 100ms 淡入淡出、響度正規化到
  `loudness_target_i`（預設 -16 LUFS），輸出到 `out/<檔名>/clips/<n>.mp3`，
  並附上時間軸歸零到 0 的 `out/<檔名>/clips/<n>.srt`。

輸出：`out/<episode>/RUN_REPORT.md`，內容包含每個 stage 的耗時、剪掉的
秒數、清理前後的響度、轉錄檔路徑、目前停用（`enabled: false`）待人工
複核的 filler 提案清單，以及一行可以直接複製貼上、在你編輯完
`plan.json` 之後拿去重跑的指令（會把 `--profile`、`--model`、`--out-dir`、
實際用到的 `--config` 檔與 `--skip` 全部釘死，確保重跑的是同一份設定與
同一個輸出目錄）。

## Dashboard（推薦）

網頁版介面，取代 Streamlit 成為推薦的日常操作方式：

```powershell
.\dashboard.ps1
.\dashboard.ps1 -Port 9000 -NoBrowser
```

第一次執行會自動建立 `.venv`、安裝 Python 依賴、檢查 ffmpeg/ffprobe，接著
（若 `web/` 存在且 `web/dist` 不是最新的）用 `npm ci && npm run build` 建置
前端，最後用 uvicorn 把 FastAPI 後端（所有路由在 `/api/*` 下）跟建置好的 SPA
一起 serve 在同一個 port（預設 8765）。需要 **Node 20+**（`web/` 的工具鏈是
Vite 6 + React 19 + TypeScript）。

- 網頁流程：episodes 列表 → 新增 episode 精靈（用路徑註冊音檔或上傳，路徑註冊
  不會複製檔案）→ 啟動 run、透過 SSE 即時看每個 stage 的進度 → review 畫面看
  波形、逐項勾選 pause/filler 提案、單獨試聽片段、存檔（存檔前會重新
  `audit`，沒過會顯示在該項目下方）→ Reapply（沿用 stage cache，只有真的被
  改動的 part 會重新 `audit`／`apply`，再重新 `assemble`）→ Deliverables 頁面
  播放最終 mp3、瀏覽並下載 clips。
- **多語系支援（i18n）**：支援繁體中文（`zh-TW`，預設）、簡體中文（`zh-CN`）、
  英文（`en`）、日文（`ja`）、韓文（`ko`）。語系解析優先級為：
  使用者於狀態列選取並儲存於 `localStorage["autopilot.locale"]` >
  瀏覽器偏好（`navigator.languages`）> 預設 `zh-TW`；
  缺漏字串自動 fallback 至英文。所有數值、時間戳記與計數均遵循 `Intl.NumberFormat` 在地化格式。
- **互動式引導導覽（Onboarding Tour）**：內建 16 步路由感知導覽，首次造訪
  （`localStorage["autopilot.tour.status"]` 為空）自動啟動。可隨時點擊狀態列右上角的
  `?` 按鈕重新播放；瀏覽器主控台執行 `localStorage.removeItem("autopilot.tour.status")`
  可重設新使用者狀態。支援鍵盤 `Escape` 跳過與 `Tab`/`Shift+Tab` 焦點循環。
- **翻譯貢獻規範**：語系辭典位於 `web/src/i18n/messages/`，以 `en.ts` 為型別單一真實來源
  （`MessageKey`），新增字串需同步更新 5 個語系檔案，參數使用 `{{param}}` 插值，
  並通過 `npm test`（`i18n-rendering.test.ts` 自動檢驗 5 語系 0 缺漏與 0 遺留未翻譯字串）。
- 完整 16 步流程與架構細節請見 [`docs/DASHBOARD.md`](docs/DASHBOARD.md)。
- **區網存取、沒有身分驗證**：uvicorn bind 在 `0.0.0.0`，同一區網的其他裝置
  可以用終端機印出的 LAN IP 連進來操作；不要把這個 port 對外網開放，也不要在
  不信任的網路上開著跑。
- `-Port <n>`：換一個 port（例如本機 8765 已被別的服務占用時）。
  `-NoBrowser`：啟動後不要自動開瀏覽器分頁。
- **取消一個 run**：畫面上的 Cancel 呼叫 `POST /api/jobs/{id}/cancel`，只在
  stage 與 stage 之間檢查取消旗標（不會中斷正在跑的單一 ffmpeg/whisper 呼叫），
  已經快取住的 stage 輸出不會被丟掉，之後重新 Run 會從快取繼續。
- 畫面截圖在 `web/screenshots/`（episodes 列表、新增精靈、即時 run 進度、
  review 畫面、clips 表格、deliverables 頁，各附桌面／手機寬度）。
- 舊的單頁 Streamlit 介面還在，但功能是 Dashboard 的子集，不再是推薦的操作
  方式：`.venv\Scripts\python -m streamlit run app.py`。

## Profile 設定值

`profiles/default.example.yaml`（複製成 `profiles/<name>.yaml` 後可自行修改，
該檔已加入 `.gitignore`，不會被提交）：

| 欄位 | 用途 |
|---|---|
| `ffmpeg_path` | ffmpeg 安裝目錄或 `ffmpeg.exe` 路徑；`null` 表示走 PATH / `tools/ffmpeg/bin` |
| `loudness_target_i` / `loudness_target_tp` | 整體響度（LUFS）/ 真峰值（dBTP）目標 |
| `denoise.engine` | `auto`\|`noisereduce`\|`afftdn`\|`off` |
| `voice_chain.*` | highpass、de-esser、compressor 各項參數 |
| `whisper_model_size` | `small`\|`medium`（`transcribe`／`plan-fillers`／`run` 的預設模型） |
| `filler_words` / `filler_pause_threshold_s` / `filler_min_probability` | 語助詞偵測門檻，見上面 `plan-fillers` 說明 |
| `pauses.*` | 停頓收緊的閾值（`noise`、`min_duration`、`max_keep`、`target`、`guard`、`min_segment`、`head`、`tail`、`max_removed_fraction`）。`noise` 預設 `"0LU"`＝相對於該檔整合響度（-16 LUFS 的 clean 檔即 -16dB、-35 LUFS 的原始檔即 -35dB）；寫 `"-35dB"` 則是絕對 dBFS 門檻。`run` 是在 clean 過的 -16 LUFS 音檔上找停頓，固定 -35dB 在那上面找不到任何超過 `max_keep` 的停頓，所以改成相對值 |

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

驗收：完整轉錄 `EP3-1.wav`（1225 秒／約 20.4 分鐘）耗時 691.4 秒，
約 1.77x 即時速度，產出 922 個 segment，`opencc_chars_changed=12`
（s2twp 後製把 12 個字從簡體/異體轉回正體）。已知限制：922 個
segment 中有 15 個（1.6%，集中在音檔開頭 10 秒內與一段 25–57
秒的區間）出現 Whisper 常見的低信心幻覺（重複字元或尾綴一個
全形「１」），這是 `small` 模型在真實錄音上的已知行為，不是程式
邏輯錯誤；其餘 907 個 segment 文字通順、時間軸正確。

完整 `run`（兩集 part、`probe -> clean -> plan-pauses -> transcribe ->
plan-fillers -> audit -> apply -> assemble`）的實測時間見
`docs/RUNS.md`。

## 已知限制

- **CPU-only 時間**：轉錄是整條 pipeline最貴的一步，`small` 模型約
  1.8–2.2x 即時速度；`medium` 模型準確度較高但更慢，本專案未在這台機器
  上做過 `medium` 的完整計時。denoise／voice chain／pause 偵測都是
  ffmpeg 單趟濾鏡，遠比轉錄快。沒有 GPU 加速路徑。
- **Whisper 幻覺**：如上，`small` 模型在真實錄音上偶爾會在低信心片段
  重複字元或吐出雜訊字元，需要人工看過 `transcript.md`／`.srt`。
- **語助詞與停頓提案都需要人工複核**：`plan-pauses` 的停頓收緊與
  `plan-fillers` 的語助詞提案都只是「提案」（後者預設
  `enabled: false`），`run` 之後務必看過 `RUN_REPORT.md` 裡列出的
  停用提案清單，或在 Streamlit 介面裡逐一勾選，不要盲目全部啟用。
- **多字語助詞抓取不保證**：「那個」「然後」這類多字語助詞能否被抓成
  一個 word，取決於 faster-whisper 的中文分詞，不是每次都切在同一個
  邊界上。
- **BGM／intro／outro 混音沒有自動響度匹配**：`assemble` 的
  sidechain ducking 用固定的 threshold/ratio/attack/release（見
  `examples/episode.example.yaml` 的 `bgm.duck`），不同素材可能需要
  手動調整這幾個參數才會聽起來自然。

## 測試

```powershell
.venv\Scripts\python.exe -m pytest -q
```

如果執行環境看不到 `.venv`（例如 sandbox 內的 reviewer），改用系統的
Python 3.12 直接裝依賴再跑：

```powershell
py -3.12 -m pip install -r requirements.txt -e .
py -3.12 -m pytest -q
```

（`faster-whisper` 的 smoke test 會透過 CLI 的 `transcribe` 指令跑
`small` 模型，第一次執行會從 Hugging Face 下載到 `tools/models/`，
需要網路；已快取則離線可跑。下載時會設定 `HF_HUB_DISABLE_SYMLINKS=1`：
Windows 沒開開發人員模式就不能建 symlink，huggingface_hub 會在下載
途中噴 `WinError 1314`，改用純檔案複製就沒這個問題。）

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
gitignored, downloaded with `HF_HUB_DISABLE_SYMLINKS=1` because symlinks
need Developer Mode on Windows and otherwise fail with WinError 1314) with `language="zh"`, `word_timestamps=True`, `vad_filter=True`.
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

### One-command run

`python -m podcast_autopilot run <episode.yaml> [--profile default]
[--model small|medium] [--skip STAGE ...] [--force] [--dry-run]` runs, per
part in the manifest, `probe -> clean -> plan-pauses -> transcribe ->
plan-fillers -> audit -> apply`, then `assemble`s all parts into one
episode. Or just run `.\run.ps1 examples\episode.example.yaml` (creates
`.venv` if missing, installs requirements, checks ffmpeg, then calls the
same command; `.\run.ps1 examples\episode.example.yaml -Profile spotify
-ExtraArgs --dry-run` forwards extra flags).

Each part caches every stage's outputs in
`out/<episode>/parts/<part>/stage_cache.json`, keyed on the source file's
sha256, the profile's sha256, and a per-stage version number (`probe` is
cached too, and `transcribe`'s key also includes the whisper model size, so
`--model medium` after a `--model small` run never reuses the old
transcript); a re-run skips a stage (`cached`) only if all three still
match and its output files still exist. `--force` ignores the cache and reruns everything.
Whenever `plan-pauses` re-runs, `plan-fillers` re-runs too (a rebuilt
pause plan no longer holds the earlier filler proposals).
`--dry-run` prints each stage's would-be status (`ran`/`cached`) without
doing anything (the preview goes to `RUN_REPORT.dry-run.md`, so the last
real run's `RUN_REPORT.md` is kept). `--skip STAGE` reuses an existing output file for that
stage (errors if it does not exist yet).

Output: `out/<episode>/RUN_REPORT.md` with per-stage timings, seconds
removed, loudness before/after cleaning, the transcript path, the list of
disabled (`enabled: false`) filler proposals to review, and a
copy-pasteable command to re-run after you hand-edit a part's `plan.json`
(it pins `--profile`, `--model`, `--out-dir`, the exact `--config` file used
and any `--skip`, so it reproduces the same configuration and output
directory; only `audit`/`apply`, and `assemble` if the rendered audio actually
changed, re-run — `clean`/`plan-pauses`/`transcribe`/`plan-fillers` stay
cached).

`examples/episode.example.yaml` points at two placeholder WAVs
(`example-part-1.wav` / `example-part-2.wav`) that are not committed (no
audio ships with this repo); `run.ps1` detects when you run that exact
bundled file and first calls `python -m podcast_autopilot make-example` to
generate synthetic tone+noise audio for them, so the one-command run works
right after a fresh clone with no real recording needed. Copy the YAML and
point `parts` at your own audio to use it for real.

### Dashboard (recommended)

A web UI that replaces Streamlit as the recommended day-to-day way to use
the tool:

```powershell
.\dashboard.ps1
.\dashboard.ps1 -Port 9000 -NoBrowser
```

First run creates/updates `.venv`, installs Python dependencies, checks
ffmpeg/ffprobe, then (if `web/` exists and `web/dist` is stale) builds the
frontend with `npm ci && npm run build`, and finally serves the FastAPI
backend (all routes under `/api/*`) and the built SPA together with
uvicorn on one port (default 8765). Requires **Node 20+** (the `web/`
toolchain is Vite 6 + React 19 + TypeScript).

- Flow: episodes list -> new-episode wizard (register a file by path or
  upload it; registering by path never copies the source) -> start a run
  and watch per-stage SSE progress -> review screen (waveform, per-item
  pause/filler toggles with inline `422` audit errors if a save fails,
  snippet playback, save) -> Reapply (same caching as the CLI: only the
  parts you actually changed re-`audit`/`apply`, then `assemble` re-runs if
  the rendered audio changed) -> Deliverables screen to play the final MP3
  and browse/download clips.
- **Localization (i18n)**: Supports Traditional Chinese (`zh-TW`, default), Simplified Chinese
  (`zh-CN`), English (`en`), Japanese (`ja`), and Korean (`ko`). Locale resolution precedence:
  user selection stored in `localStorage["autopilot.locale"]` > browser preference (`navigator.languages`) > default `zh-TW`;
  missing keys fall back to English. All numbers, durations, and counts follow `Intl.NumberFormat` localization.
- **Onboarding Guide (Tour)**: Built-in 16-step route-aware interactive tour that auto-launches on first visit
  (`localStorage["autopilot.tour.status"]` is empty). Replay at any time via the `?` button on the top-right
  of the status bar; reset first-time state via `localStorage.removeItem("autopilot.tour.status")`.
  Supports `Escape` to dismiss and `Tab`/`Shift+Tab` focus cycling.
- **Translation Contribution Rules**: Catalogs live under `web/src/i18n/messages/`, keyed by `en.ts` as the single
  source of truth (`MessageKey`). Additions must update all 5 locale catalogs, use `{{param}}` interpolation,
  and pass `npm test` (`i18n-rendering.test.ts` validates zero missing keys and zero unlocalized strings).
- Detailed 16-step guide and architecture reference: [`docs/DASHBOARD.md`](docs/DASHBOARD.md).
- **LAN-reachable, no authentication**: uvicorn binds `0.0.0.0`, so other
  devices on the same network can reach it at the LAN IP printed at
  startup. Do not expose this port to the internet or run it on an
  untrusted network.
- `-Port <n>` picks a different port (e.g. if 8765 is already taken by
  something else). `-NoBrowser` skips auto-opening a browser tab.
- **Cancelling a run**: the UI's Cancel button calls
  `POST /api/jobs/{id}/cancel`, which is checked between pipeline stages
  only (it does not interrupt an in-flight ffmpeg/whisper call); stage
  outputs already cached are kept, so a subsequent Run resumes from cache.
- Screenshots in `web/screenshots/` (episodes list, new-episode wizard,
  live run progress, review screen, clips table, deliverables screen, each
  at desktop and mobile widths).
- The old single-page Streamlit app is still there but is a functional
  subset of the dashboard, no longer the recommended way to use the tool:
  `.venv\Scripts\python -m streamlit run app.py`.

### Profile keys

Copy `profiles/default.example.yaml` to `profiles/<name>.yaml` (gitignored,
so edits are never committed):

| Key | Purpose |
|---|---|
| `ffmpeg_path` | ffmpeg install dir or `ffmpeg.exe` path; `null` = PATH / `tools/ffmpeg/bin` |
| `loudness_target_i` / `loudness_target_tp` | integrated loudness (LUFS) / true peak (dBTP) target |
| `denoise.engine` | `auto`\|`noisereduce`\|`afftdn`\|`off` |
| `voice_chain.*` | highpass, de-esser, compressor parameters |
| `whisper_model_size` | `small`\|`medium`, default model for `transcribe`/`plan-fillers`/`run` |
| `filler_words` / `filler_pause_threshold_s` / `filler_min_probability` | filler-word detection thresholds |
| `pauses.*` | pause-tightening thresholds (`noise`, `min_duration`, `max_keep`, `target`, `guard`, `min_segment`, `head`, `tail`, `max_removed_fraction`). `noise` defaults to `"0LU"` = relative to the file's integrated loudness (-16dB on a -16 LUFS cleaned part, -35dB on a -35 LUFS raw take); `"-35dB"` is an absolute dBFS threshold. `run` detects pauses on the cleaned -16 LUFS audio, where a fixed -35dB never finds a pause longer than `max_keep` |

### Reviewing plan.json

Every stage that proposes an edit (`plan-pauses`, `plan-fillers`) writes to
`out/<episode>/parts/<part>/plan.json` rather than rendering directly.
Pause cuts default to `enabled: true`; filler-word proposals default to
`enabled: false` since they are lower-confidence. Before trusting the
final MP3, open `RUN_REPORT.md`'s disabled-proposal table (or the
Streamlit checkboxes) and flip `enabled` only on the filler cuts you agree
with, then re-run the printed re-apply command — caching means this only
re-renders `audit`/`apply`/`assemble` for the part(s) you touched.

### Known limitations

- **CPU-only timing**: transcription is the most expensive stage —
  `small` runs at roughly 1.8-2.2x real time; `medium` is more accurate
  but has not been benchmarked end-to-end on this machine. Denoise, the
  voice chain, and pause detection are single-pass ffmpeg filters, far
  cheaper than transcription. There is no GPU path.
- **Whisper hallucination**: the `small` model occasionally repeats
  characters or emits stray characters on low-confidence segments in real
  recordings; always spot-check `transcript.md`/`.srt`.
- **Pause and filler proposals need human review**: `plan-pauses` cuts and
  `plan-fillers` proposals (the latter `enabled: false` by default) are
  proposals, not final decisions — always check `RUN_REPORT.md`'s disabled
  list or the Streamlit checkboxes before treating a `run` as final.
- **Multi-character filler words are not guaranteed to be caught as one
  word**: whether "那個"/"然後" tokenize as a single word depends on
  faster-whisper's Chinese word segmentation.
- **BGM/intro/outro mixing has no automatic loudness matching**:
  `assemble`'s sidechain ducking uses fixed threshold/ratio/attack/release
  values (see `examples/episode.example.yaml`'s `bgm.duck`); different
  source material may need those tuned by hand to sound natural.

See `docs/RUNS.md` for a real end-to-end `run` timing/quality record.

Architectural reference: Hao0321/video-autopilot-kit (see `NOTICE`).
License: MIT.
