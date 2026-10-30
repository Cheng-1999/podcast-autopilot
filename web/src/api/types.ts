export type EpisodeStatus =
  | "never-run"
  | "running"
  | "needs-review"
  | "done"
  | "failed"
  | "invalid";

export interface EpisodeSummary {
  id: string;
  path: string;
  example: boolean;
  title: string | null;
  episode: number | null;
  parts: string[];
  status: EpisodeStatus;
  last_run_time: number | null;
  final_mp3: string | null;
  duration: number | null;
  lufs: number | null;
  job_id: string | null;
  error?: string | null;
  tags?: { artist?: string | null; album?: string | null; year?: number | null; comment?: string | null };
}

export interface StageDetail {
  name: string;
  status: string;
  elapsed: number | null;
}

export interface PartDetail {
  stem: string;
  source: string | null;
  loudness_before: string | null;
  loudness_after: string | null;
  seconds_removed: number | null;
  transcript: string | null;
  plan: string | null;
  stages: StageDetail[];
  disabled_filler_proposals: Array<{
    id: string;
    start: number;
    end: number;
    reason: string;
  }>;
}

export interface AssemblyDetail {
  status?: string;
  output?: string;
  receipt?: string;
  duration?: number | null;
  loudness?: string | null;
}

export interface EpisodeDetail extends EpisodeSummary {
  report_available: boolean;
  parts_detail: PartDetail[];
  assembly: AssemblyDetail;
  reapply_command: string | null;
}

export interface HealthResponse {
  ffmpeg: string | null;
  ffprobe: string | null;
  ffmpeg_ok: boolean;
  whisper_models: Record<string, boolean>;
  free_disk_gb: number | null;
}

export interface JobEventPayload {
  seq: number;
  event: string;
  stage?: string | null;
  part?: string | null;
  elapsed?: number;
  message?: string;
  ts?: number;
}

export interface JobStateResponse {
  id: string;
  episode_id: string;
  profile: string;
  model: string;
  force: boolean;
  skip: string[];
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  error: string | null;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
  log_path: string | null;
  event_count: number;
}

export interface RunRequestBody {
  profile?: string;
  model?: string;
  force?: boolean;
  skip?: string[];
}

export type PlanItemKind = "keep" | "cut" | "fade" | "filler" | "clip";

export interface PlanItem {
  id: string;
  kind: PlanItemKind | string;
  start: number;
  end: number;
  reason: string;
  enabled: boolean;
}

export interface PlanSource {
  path: string;
  sha256: string;
  duration: number;
  sr: number;
  channels: number;
}

export interface PlanResponse {
  schema: string;
  created: string;
  source: PlanSource;
  profile: unknown;
  items: PlanItem[];
  render?: unknown;
  predicted_duration?: number;
}

export interface PlanPutResult {
  ok: boolean;
  seconds_removed?: number;
  coverage_ratio?: number;
  errors?: string[];
}

export interface ManualCutResult {
  ok: boolean;
  id?: string;
  seconds_removed?: number;
  coverage_ratio?: number;
  errors?: string[];
}

export interface AISuggestedCut {
  start: number;
  end: number;
  reason: string;
  valid: boolean;
  errors: string[];
}

export interface AISuggestResult {
  ok: boolean;
  suggestions: AISuggestedCut[];
}

export interface TranscriptWord {
  word: string;
  start: number;
  end: number;
  probability: number;
}

export interface TranscriptSegment {
  id: number;
  start: number;
  end: number;
  text: string;
  words?: TranscriptWord[];
}

export interface TranscriptResponse {
  language: string;
  duration: number;
  segments: TranscriptSegment[];
}

export interface PeaksResponse {
  wav_sha256: string;
  buckets: number;
  peaks: number[][];
}

export interface DeliverableClip {
  mp3: string | null;
  srt: string | null;
}

export interface DeliverablePart {
  part: string;
  edited_wav: string | null;
  clips: DeliverableClip[];
}

export interface DeliverablesResponse {
  final_mp3: string | null;
  chapters_json: string | null;
  receipt: string | null;
  parts: DeliverablePart[];
}

export interface ReceiptData {
  schema: string;
  created: string;
  duration: number;
  loudness: {
    input_i: number;
    input_tp: number;
  };
  output: { path: string; sha256: string };
}

export interface ChapterEntry {
  start: number;
  end: number;
  title: string;
}

export interface UploadResponse {
  path: string;
  duration: number;
  sr: number;
  channels: number;
}

export interface ChapterInput { start: string; title: string }
export interface EpisodeCreateBody {
  title: string; episode: number; parts: string[];
  intro?: string | null; outro?: string | null;
  bgm?: { path: string; gain_db?: number; duck?: { threshold?: number; ratio?: number; attack?: number; release?: number } } | null;
  chapters: ChapterInput[];
  tags: Record<string, string | number | null>;
}

export interface ClipCandidate {
  id: string | number; start: number; end: number; text: string;
  score: number; score_components?: Record<string, number>; rerank?: number;
  rendered?: { mp3: string | null; srt: string | null };
}
export interface ClipsResponse { candidates: ClipCandidate[]; source?: { path?: string | null; duration?: number | null }; }
