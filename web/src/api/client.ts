import type {
  EpisodeSummary,
  EpisodeDetail,
  HealthResponse,
  JobStateResponse,
  RunRequestBody,
  JobEventPayload,
  UploadResponse, EpisodeCreateBody, ClipsResponse,
  PlanResponse, PlanPutResult, TranscriptResponse, PeaksResponse, DeliverablesResponse,
} from "./types";

const API_BASE = "/api";

export async function fetchHealth(): Promise<HealthResponse> {
  const resp = await fetch(`${API_BASE}/health`);
  if (!resp.ok) {
    throw new Error(`Health check failed: ${resp.status}`);
  }
  return resp.json();
}

async function jsonRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init);
  if (!resp.ok) throw new Error((await resp.text()) || `${resp.status} ${resp.statusText}`);
  return resp.json();
}

export function uploadFile(file: File, episode = "_uploads", onProgress?: (value: number) => void): Promise<UploadResponse> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/uploads`);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress?.(e.loaded / e.total); };
    xhr.onload = () => xhr.status >= 200 && xhr.status < 300 ? resolve(JSON.parse(xhr.responseText)) : reject(new Error(xhr.responseText || `Upload failed: ${xhr.status}`));
    xhr.onerror = () => reject(new Error("Upload failed"));
    const form = new FormData(); form.append("file", file); form.append("episode", episode); xhr.send(form);
  });
}

export function registerLocalPath(path: string): Promise<UploadResponse> {
  return jsonRequest(`${API_BASE}/uploads`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path }) });
}
export function createEpisode(body: EpisodeCreateBody): Promise<{ id: string; path: string }> {
  return jsonRequest(`${API_BASE}/episodes`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}
export function fetchClips(episodeId: string, partId: string): Promise<ClipsResponse> {
  return jsonRequest(`${API_BASE}/episodes/${encodeURIComponent(episodeId)}/parts/${encodeURIComponent(partId)}/clips`);
}
export function generateClips(episodeId: string, partId: string, render: boolean): Promise<JobStateResponse> {
  return jsonRequest(`${API_BASE}/episodes/${encodeURIComponent(episodeId)}/parts/${encodeURIComponent(partId)}/clips`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ render }) });
}

export function mediaUrl(episodeId: string, relPath: string): string {
  return `${API_BASE}/media/${encodeURIComponent(episodeId)}/${relPath}`;
}

export function fetchPlan(episodeId: string, partId: string): Promise<PlanResponse> {
  return jsonRequest(`${API_BASE}/episodes/${encodeURIComponent(episodeId)}/parts/${encodeURIComponent(partId)}/plan`);
}

export async function putPlan(
  episodeId: string,
  partId: string,
  flags: Array<{ id: string; enabled: boolean }>
): Promise<PlanPutResult> {
  const resp = await fetch(
    `${API_BASE}/episodes/${encodeURIComponent(episodeId)}/parts/${encodeURIComponent(partId)}/plan`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(flags),
    }
  );
  // 422 carries a structured { ok: false, errors: string[] } body (audit
  // failure) rather than a generic error, so parse it instead of throwing.
  if (resp.status === 422) return resp.json();
  if (!resp.ok) throw new Error((await resp.text()) || `${resp.status} ${resp.statusText}`);
  return resp.json();
}

export function fetchTranscript(episodeId: string, partId: string): Promise<TranscriptResponse> {
  return jsonRequest(`${API_BASE}/episodes/${encodeURIComponent(episodeId)}/parts/${encodeURIComponent(partId)}/transcript`);
}

export function fetchPeaks(episodeId: string, partId: string, buckets = 2000): Promise<PeaksResponse> {
  return jsonRequest(
    `${API_BASE}/episodes/${encodeURIComponent(episodeId)}/parts/${encodeURIComponent(partId)}/peaks?buckets=${buckets}`
  );
}

export function fetchDeliverables(episodeId: string): Promise<DeliverablesResponse> {
  return jsonRequest(`${API_BASE}/episodes/${encodeURIComponent(episodeId)}/deliverables`);
}

/** Fetches a JSON file served under a plain (same-origin) URL, e.g. a
 * `/api/media/...` link returned by the deliverables endpoint. */
export function fetchJson<T>(url: string): Promise<T> {
  return jsonRequest<T>(url);
}

/** Best-effort parse of the `--profile <x>` / `--model <x>` flags out of the
 * `reapply_command` string reported by GET /episodes/{id} (e.g.
 * "python -m podcast_autopilot run examples\\ep3.local.yaml --profile default"),
 * so re-apply from the review screen uses the same settings as the last run. */
export function parseReapplyOptions(reapplyCommand: string | null): { profile: string; model?: string } {
  if (!reapplyCommand) return { profile: "default" };
  const profileMatch = reapplyCommand.match(/--profile\s+(\S+)/);
  const modelMatch = reapplyCommand.match(/--model\s+(\S+)/);
  return {
    profile: profileMatch?.[1] ?? "default",
    model: modelMatch?.[1],
  };
}

export async function fetchEpisodes(): Promise<EpisodeSummary[]> {
  const resp = await fetch(`${API_BASE}/episodes`);
  if (!resp.ok) {
    throw new Error(`Failed to fetch episodes: ${resp.status}`);
  }
  return resp.json();
}

export async function fetchEpisode(episodeId: string): Promise<EpisodeDetail> {
  const resp = await fetch(`${API_BASE}/episodes/${encodeURIComponent(episodeId)}`);
  if (!resp.ok) {
    throw new Error(`Failed to fetch episode: ${resp.status}`);
  }
  return resp.json();
}

export async function fetchReport(episodeId: string): Promise<string> {
  const resp = await fetch(`${API_BASE}/episodes/${encodeURIComponent(episodeId)}/report`);
  if (!resp.ok) {
    throw new Error(`Failed to fetch report: ${resp.status}`);
  }
  return resp.text();
}

export async function runEpisode(
  episodeId: string,
  body: RunRequestBody
): Promise<JobStateResponse> {
  const resp = await fetch(`${API_BASE}/episodes/${encodeURIComponent(episodeId)}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Failed to run episode: ${text || resp.statusText}`);
  }
  return resp.json();
}

export async function cancelJob(jobId: string): Promise<JobStateResponse> {
  const resp = await fetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  });
  if (!resp.ok) {
    throw new Error(`Failed to cancel job: ${resp.status}`);
  }
  return resp.json();
}

export async function fetchJob(jobId: string): Promise<JobStateResponse> {
  const resp = await fetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}`);
  if (!resp.ok) {
    throw new Error(`Failed to fetch job: ${resp.status}`);
  }
  return resp.json();
}

export async function fetchProfiles(): Promise<string[]> {
  try {
    const resp = await fetch(`${API_BASE}/profiles`);
    if (resp.ok) {
      const data = await resp.json();
      if (Array.isArray(data) && data.length > 0) return data;
    }
  } catch {
    // fallback
  }
  return ["default", "spotify"];
}

export function createJobEventSource(
  jobId: string,
  onEvent: (payload: JobEventPayload) => void,
  onError?: (err: Event) => void
): () => void {
  const url = `${API_BASE}/jobs/${encodeURIComponent(jobId)}/events`;
  const es = new EventSource(url);

  es.onmessage = (e) => {
    try {
      const parsed: JobEventPayload = JSON.parse(e.data);
      onEvent(parsed);
    } catch (err) {
      console.error("SSE JSON parse error:", err);
    }
  };

  // Custom events might also be dispatched as event: <name>
  const handleGenericEvent = (e: MessageEvent) => {
    try {
      const parsed: JobEventPayload = JSON.parse(e.data);
      onEvent(parsed);
    } catch {
      // ignore
    }
  };

  const knownEvents = [
    "job_started",
    "job_finished",
    "job_cancelled",
    "job_failed",
    "log",
    "started",
    "finished",
    "cached",
    "skipped",
  ];

  for (const ev of knownEvents) {
    es.addEventListener(ev, handleGenericEvent);
  }

  es.onerror = (e) => {
    if (onError) onError(e);
  };

  return () => {
    es.close();
  };
}
