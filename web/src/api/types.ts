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
