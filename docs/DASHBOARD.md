# Dashboard Documentation: Localization & Onboarding Guide

This document provides a comprehensive guide to the **podcast-autopilot** web dashboard, covering supported locales, locale resolution precedence, the interactive onboarding guide tour, translation contribution rules, and the complete user workflow.

---

## 1. Overview & Architecture

The podcast-autopilot dashboard provides a modern web interface for automated podcast editing, replacing the previous Streamlit prototype as the recommended day-to-day interface.

- **Backend**: FastAPI (`src/podcast_autopilot/server/`) serving all API routes under `/api/*`.
- **Frontend**: Vite 6 + React 19 + TypeScript single-page application (`web/`) styled with the `desk-dense` design token family and IBM Plex Sans/Mono and Noto Sans TC typography.
- **Serving**: `dashboard.ps1` compiles the frontend (if needed) and serves both the backend API and the compiled static assets (`web/dist/`) together via `uvicorn` on a single port (default `8765`, LAN-accessible, no authentication).

---

## 2. Localization (i18n)

The dashboard frontend includes a fully typed internationalization subsystem located under [`web/src/i18n/`](../web/src/i18n/).

### Supported Locales

The dashboard currently supports five locales:

| Locale Code | Language Name | Display Label | Catalog File | Status |
| :--- | :--- | :--- | :--- | :--- |
| `zh-TW` | Traditional Chinese (正體中文) | 繁體中文 | [`web/src/i18n/messages/zh-TW.ts`](../web/src/i18n/messages/zh-TW.ts) | Default / Complete |
| `zh-CN` | Simplified Chinese (简体中文) | 简体中文 | [`web/src/i18n/messages/zh-CN.ts`](../web/src/i18n/messages/zh-CN.ts) | Complete |
| `en` | English | English | [`web/src/i18n/messages/en.ts`](../web/src/i18n/messages/en.ts) | Base Catalog / Source of Truth |
| `ja` | Japanese (日本語) | 日本語 | [`web/src/i18n/messages/ja.ts`](../web/src/i18n/messages/ja.ts) | Complete |
| `ko` | Korean (한국어) | 한국어 | [`web/src/i18n/messages/ko.ts`](../web/src/i18n/messages/ko.ts) | Complete |

### Locale Resolution Precedence

When a user visits the dashboard, the active locale is resolved following this exact hierarchy (see [`web/src/i18n/storage.ts`](../web/src/i18n/storage.ts)):

```
1. Explicit User Preference (localStorage["autopilot.locale"])
                       ↓ (if not set)
2. Browser Language Preference (navigator.languages)
                       ↓ (if no match)
3. Default Application Locale ("zh-TW")
```

1. **Explicit User Selection (`localStorage`)**:
   - If the user has explicitly chosen a language via the status bar dropdown (`#language-select`), the selection is stored in `window.localStorage` under key `autopilot.locale`.
   - On subsequent visits or page reloads, this stored value takes top priority.
2. **Browser Language Matching (`navigator.languages`)**:
   - If no valid stored locale exists, the system inspects `navigator.languages` (or `navigator.language`):
     - Tags starting with `zh` containing `hans` or ending with `-cn` / `-sg` map to `zh-CN`.
     - All other Chinese tags (`zh-TW`, `zh-HK`, `zh-MO`, or bare `zh`) map to `zh-TW`.
     - Tags starting with `en` map to `en`.
     - Tags starting with `ja` map to `ja`.
     - Tags starting with `ko` map to `ko`.
3. **Default Fallback**:
   - If none of the user's preferred browser languages match a supported locale, `zh-TW` is used.
4. **Key-Level Fallback (Forward Compatibility)**:
   - If an individual message key is missing in a specific language catalog, [`resolveMessage()`](../web/src/i18n/messages/index.ts) falls back to the English (`en`) catalog string.

### Document Language & Formatting

- Setting or switching a locale automatically updates `<html lang="...">` on the root document element.
- All numbers, percentages, durations, and counts use the locale-aware formatting utilities in [`web/src/lib/format.ts`](../web/src/lib/format.ts):
  - `formatDecimal(value, locale, digits)`: Decimal formatting via `Intl.NumberFormat`.
  - `formatCount(value, locale)`: Integer counts with grouping separators.
  - `formatMinutesSeconds(seconds, locale)`: Formats timestamps as `MM:SS` or `H:MM:SS`.

---

## 3. Interactive Onboarding Guide (Tour)

The dashboard features a route-aware interactive onboarding guide implemented in [`web/src/tour/`](../web/src/tour/).

### Behavior & Auto-Start

- **First-Time Visitors**: The tour automatically starts on initial page load when no status is recorded in `localStorage` (`autopilot.tour.status === null`).
- **Completion & Dismissal**:
  - Advancing through all steps marks the tour as `completed`.
  - Skipping or escaping the tour marks the tour as `dismissed`.
  - In both cases, the status is persisted to `localStorage` under `autopilot.tour.status` so it will not auto-start again on subsequent visits.

### How to Replay the Tour

Users can restart the onboarding guide at any time:
- **Status Bar Replay Button**: Click the `?` button located on the right side of the top status bar ([`StatusBar.tsx`](../web/src/components/StatusBar.tsx)). It triggers `tour.replay()` and launches the guide from step 1 on the current view.
- **Resetting First-Time Auto-Start**: To restore the first-time visitor experience, clear the persisted storage key in browser developer tools:
  ```javascript
  localStorage.removeItem("autopilot.tour.status");
  ```
  Then reload the page.

### Navigation & Accessibility

- **Spotlight & Positioning**: [`TourOverlay.tsx`](../web/src/tour/TourOverlay.tsx) computes target bounding boxes dynamically (`data-tour="<anchor>"`) and places the dialog with collision-avoiding viewport clamping.
- **Cross-Route Navigation**: When a tour step targets another route, [`TourContext`](../web/src/tour/context.tsx) automatically navigates the router to the target path.
- **Keyboard Navigation**:
  - `Escape`: Instantly skips and dismisses the tour.
  - `Tab` / `Shift+Tab`: Focus-trapped within the tour dialog buttons (Skip, Back, Next/Finish) with cyclic wrapping.
- **Context-Aware Scoping**: If launched from the episodes list without an episode ID selected, the tour automatically filters out episode-specific steps and guides through global features and episode creation. When launched inside an episode (`/episodes/:id`), all 16 steps are accessible.

---

## 4. Complete User Workflow (16 Guide Steps)

The guide covers the complete end-to-end podcast post-production workflow across 16 declarative steps:

| Step # | Step ID | Anchor Target | Route Scope | Description |
| :---: | :--- | :--- | :--- | :--- |
| **1** | `status-bar` | `status-bar` | Global (`any`) | **Global Status & Health**: Displays active pipeline jobs, FFmpeg/ffprobe readiness, cached Whisper models, disk space, LAN IP, language selector, and tour replay button. |
| **2** | `episodes-list` | `episodes-list` | `/episodes` | **Episodes Catalog**: Table showing all discovered podcast episodes, IDs, status tags, duration, part counts, and navigation shortcuts. |
| **3** | `episodes-new` | `episodes-new` | `/episodes` | **New Episode Action**: Primary button to open the episode registration wizard. |
| **4** | `wizard-steps` | `wizard-steps` | `/episodes/new` | **Wizard Stages**: 3-step structured creation workflow covering metadata, audio tracks, and background music / assets. |
| **5** | `wizard-upload` | `wizard-upload` | `/episodes/new` | **Audio Sources Intake**: Register existing audio files on local disk (zero-copy) or upload recordings through the browser. |
| **6** | `run-controls` | `run-controls` | `/episodes/:id` | **Pipeline Execution Controls**: Select profile, choose Whisper transcription model (`small`, `medium`, or `large-v3`), specify stages to skip, and trigger pipeline execution. |
| **7** | `stage-grid` | `stage-grid` | `/episodes/:id` | **Live Stage Progress Grid**: Real-time SSE visualization of all processing stages (`probe`, `clean`, `plan-pauses`, `transcribe`, `plan-fillers`, `audit`, `apply`, `assemble`) across each part. |
| **8** | `log-panel` | `log-panel` | `/episodes/:id` | **Real-Time Log Tail**: Live console output streaming stdout/stderr from backend FFmpeg and Whisper subprocesses. |
| **9** | `item-list` | `item-list` | `/episodes/:id/review` | **Edit Plan Items**: Table of pause tightening and filler word proposals with interactive toggle checkboxes, reason codes, and inline audit validation. |
| **10** | `waveform` | `waveform` | `/episodes/:id/review` | **Interactive Waveform**: High-performance audio waveform display synchronized with plan items and audio playback preview. |
| **11** | `review-reapply` | `review-reapply` | `/episodes/:id/review` | **Save & Reapply**: Saves modified edit plans and triggers an intelligent cached re-render where only modified segments are recomputed. |
| **12** | `clips-generate` | `clips-generate` | `/episodes/:id/clips` | **Social Clips Generator**: Automatic candidate extraction from transcripts using sentence boundaries, pause detection, keyword scoring, and optional Claude ranking. |
| **13** | `clips-play` | `clips-play` | `/episodes/:id/clips` | **Clip Preview Player**: In-browser audio player with synchronized sentence-level subtitle display. |
| **14** | `clips-download` | `clips-download` | `/episodes/:id/clips` | **Clip Exports**: Download individual rendered social clip MP3s and time-aligned SRT subtitle files. |
| **15** | `deliverables-download` | `deliverables-download` | `/episodes/:id/deliverables` | **Master Deliverables**: Play and download the final assembled episode MP3 with integrated loudness compliance (-16 LUFS / -1.5 dBTP) and chapter markers. |
| **16** | `deliverables-report` | `deliverables-report` | `/episodes/:id/deliverables` | **Run Report & Audit**: Detailed execution report (`RUN_REPORT.md`) containing per-stage processing timings, seconds removed, and reproducible CLI commands. |

---

## 5. Translation Contribution Rules

When contributing new user-facing features or modifying copy, follow these strict contribution standards:

### File Structure

All translations live in [`web/src/i18n/messages/`](../web/src/i18n/messages/):
- `en.ts`: Canonical English message catalog. The TypeScript type `MessageKey` is defined directly as `keyof typeof en`.
- `zh-TW.ts`: Traditional Chinese translations.
- `zh-CN.ts`: Simplified Chinese translations.
- `ja.ts`: Japanese translations.
- `ko.ts`: Korean translations.
- `index.ts`: Catalog exports and message resolver.

### Contribution Rules

1. **English is the Source of Truth**:
   - Every new string MUST first be added to [`en.ts`](../web/src/i18n/messages/en.ts).
   - The key name should follow existing namespace dot-notation (e.g. `nav.*`, `status.*`, `tour.step.*`, `review.*`, `clips.*`).
2. **Synchronize All Five Catalogs**:
   - A pull request or change must provide translations in **all five files** (`en.ts`, `zh-TW.ts`, `zh-CN.ts`, `ja.ts`, `ko.ts`).
   - Partial keys or missing translations in non-English catalogs are forbidden by automated tests.
3. **Parameter Interpolation**:
   - Use double curly braces for dynamic variables, e.g. `"tour.progress": "{{current}} / {{total}}"`.
   - Call via `t("tour.progress", { current: 1, total: 5 })`.
4. **Formatting Utilities**:
   - NEVER use raw `.toFixed()` or manual string concatenation for numbers or times in components.
   - Always import and use `formatDecimal()`, `formatCount()`, or `formatMinutesSeconds()` from `web/src/lib/format.ts`.
5. **Desk-Dense Aesthetic Compliance**:
   - Keep labels concise and high-information-density in keeping with the `desk-dense` design system.
   - Avoid verbose explanations where concise tabular labels suffice.
6. **Automated Verification**:
   - Run the test suite before committing:
     ```bash
     npm test
     npm run lint
     npm run build
     ```
   - [`web/test/i18n.test.ts`](../web/test/i18n.test.ts) asserts catalog integrity and fallback mechanics.
   - [`web/test/i18n-rendering.test.ts`](../web/test/i18n-rendering.test.ts) performs server rendering across all 5 locales to verify there are 0 missing keys, 0 unreplaced `{{placeholder}}` strings, and 0 leftover hardcoded strings.

---

## 6. Testing & Quality Verification

To verify the dashboard and all localization/tour capabilities:

```powershell
# 1. Frontend unit & integration tests (vitest)
npm test

# 2. Frontend lint check (ESLint)
npm run lint

# 3. TypeScript & production asset build
npm run build

# 4. Playwright End-to-End smoke suite
npm run e2e

# 5. Backend Python suite (pytest)
.\.venv\Scripts\python.exe -m pytest
```
