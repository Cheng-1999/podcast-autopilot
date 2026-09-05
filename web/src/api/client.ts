import type {
  EpisodeSummary,
  EpisodeDetail,
  HealthResponse,
  JobStateResponse,
  RunRequestBody,
  JobEventPayload,
} from "./types";

const API_BASE = "/api";

export async function fetchHealth(): Promise<HealthResponse> {
  const resp = await fetch(`${API_BASE}/health`);
  if (!resp.ok) {
    throw new Error(`Health check failed: ${resp.status}`);
  }
  return resp.json();
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
