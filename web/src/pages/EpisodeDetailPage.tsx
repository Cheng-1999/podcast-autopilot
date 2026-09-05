import React, { useEffect, useReducer, useState, useCallback, useRef } from "react";
import { useParams, Link, useNavigate, useLocation } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchEpisode,
  fetchReport,
  fetchProfiles,
  runEpisode,
  cancelJob,
  createJobEventSource,
} from "../api/client";
import { runStateReducer, INITIAL_RUN_STATE } from "../api/sse";
import { getStatusDisplay } from "../api/status";
import { RunControls } from "../components/RunControls";
import { StageGrid } from "../components/StageGrid";
import { LogPanel } from "../components/LogPanel";
import { RunReportView } from "../components/RunReportView";
import type { EpisodeDetail } from "../api/types";

export const EpisodeDetailPage: React.FC = () => {
  const { id = "" } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();

  const [runState, dispatch] = useReducer(runStateReducer, INITIAL_RUN_STATE);
  const [isLogOpen, setIsLogOpen] = useState<boolean>(true);
  const eventSourceCleanupRef = useRef<(() => void) | null>(null);
  const reapplyCaption = (location.state as { reapplyCaption?: string } | null)?.reapplyCaption ?? null;

  // Fetch episode detail
  const {
    data: episode,
    isLoading: isEpLoading,
    error: epError,
    refetch: refetchEpisode,
  } = useQuery<EpisodeDetail>({
    queryKey: ["episode", id],
    queryFn: () => fetchEpisode(id),
    enabled: Boolean(id),
  });

  // Fetch report markdown
  const {
    data: reportContent,
    refetch: refetchReport,
  } = useQuery<string>({
    queryKey: ["report", id],
    queryFn: () => fetchReport(id),
    enabled: Boolean(id && episode?.report_available),
    retry: false,
  });

  // Fetch profiles
  const { data: profiles = ["default", "spotify"] } = useQuery<string[]>({
    queryKey: ["profiles"],
    queryFn: fetchProfiles,
  });

  // Initialize stages when episode loads and not running
  useEffect(() => {
    if (episode && runState.status === "idle") {
      const parts =
        episode.parts_detail && episode.parts_detail.length > 0
          ? episode.parts_detail
          : (episode.parts || []).map((p) => ({
              stem: p.replace(/\.[^/.]+$/, ""),
              stages: [],
            }));

      dispatch({
        type: "INIT_STAGES",
        parts: parts.map((p) => ({
          stem: p.stem,
          stages: p.stages,
        })),
        assemblyStatus: episode.assembly?.status,
      });
    }
  }, [episode, runState.status]);

  // Connect SSE function
  const connectSSE = useCallback(
    (jobId: string) => {
      if (eventSourceCleanupRef.current) {
        eventSourceCleanupRef.current();
      }

      const cleanup = createJobEventSource(
        jobId,
        (evt) => {
          dispatch({ type: "SSE_EVENT", payload: evt });
          if (evt.event === "job_finished") {
            // Refetch episode detail and report
            queryClient.invalidateQueries({ queryKey: ["episode", id] });
            queryClient.invalidateQueries({ queryKey: ["episodes"] });
            refetchEpisode();
            refetchReport();
          }
        },
        () => {
          // onerror
        }
      );

      eventSourceCleanupRef.current = cleanup;
    },
    [id, queryClient, refetchEpisode, refetchReport]
  );

  // If episode has active job on load, attach to it
  useEffect(() => {
    if (episode?.job_id && runState.status === "idle") {
      dispatch({ type: "RESET", jobId: episode.job_id });
      connectSSE(episode.job_id);
    }
  }, [episode?.job_id, runState.status, connectSSE]);

  // Clean up SSE on unmount
  useEffect(() => {
    return () => {
      if (eventSourceCleanupRef.current) {
        eventSourceCleanupRef.current();
      }
    };
  }, []);

  // Run handler
  const handleRun = useCallback(
    async (options: { profile: string; model: string; force: boolean; skip: string[] }) => {
      try {
        const job = await runEpisode(id, options);
        dispatch({ type: "RESET", jobId: job.id });

        // Pre-initialize parts for stage grid
        const parts =
          episode?.parts_detail && episode.parts_detail.length > 0
            ? episode.parts_detail
            : (episode?.parts || []).map((p) => ({
                stem: p.replace(/\.[^/.]+$/, ""),
                stages: [],
              }));

        dispatch({
          type: "INIT_STAGES",
          parts: parts.map((p) => ({ stem: p.stem })),
        });

        connectSSE(job.id);
        setIsLogOpen(true);
      } catch (err) {
        alert(`啟動執行失敗: ${(err as Error).message}`);
      }
    },
    [id, episode, connectSSE]
  );

  // Cancel handler
  const handleCancel = useCallback(async () => {
    if (!runState.jobId) return;
    try {
      await cancelJob(runState.jobId);
      dispatch({ type: "CANCEL" });
    } catch (err) {
      console.error("Cancel failed:", err);
    }
  }, [runState.jobId]);

  // Keyboard shortcut listener: 'r' for run (if not focused on inputs)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) {
        return;
      }
      if (e.key === "r" || e.key === "R") {
        if (runState.status !== "running") {
          e.preventDefault();
          handleRun({ profile: "default", model: "medium", force: false, skip: [] });
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [runState.status, handleRun]);

  const isRunning = runState.status === "running";
  const statusInfo = getStatusDisplay(isRunning ? "running" : episode?.status);

  const partsForGrid =
    episode?.parts_detail && episode.parts_detail.length > 0
      ? episode.parts_detail.map((p) => ({ stem: p.stem }))
      : (episode?.parts || []).map((p) => ({ stem: p.replace(/\.[^/.]+$/, "") }));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      {/* Top breadcrumb & sub-nav */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "8px",
          paddingBottom: "8px",
          borderBottom: "var(--border-subtle)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: "8px" }}>
          <button
            type="button"
            className="dense-btn"
            onClick={() => navigate("/episodes")}
            style={{ height: "24px" }}
          >
            ← 返回列表
            <span className="kbd-hint">g e</span>
          </button>

          <span className="mono" style={{ color: "var(--text-muted)" }}>
            /
          </span>

          <span className="mono" style={{ fontWeight: 600, color: "var(--text-primary)" }}>
            {episode?.episode ? `EP${episode.episode.toString().padStart(2, "0")}` : id}
          </span>

          <span style={{ color: "var(--text-primary)" }}>{episode?.title || id}</span>

          <div style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
            <span className={`status-dot ${statusInfo.color}`} />
            <span
              style={{
                color:
                  statusInfo.color === "green"
                    ? "var(--semantic-green)"
                    : statusInfo.color === "blue"
                    ? "var(--semantic-blue)"
                    : statusInfo.color === "amber"
                    ? "var(--semantic-amber)"
                    : statusInfo.color === "red"
                    ? "var(--semantic-red)"
                    : "var(--text-muted)",
                fontSize: "var(--font-size-xs)",
                fontWeight: 500,
              }}
            >
              {statusInfo.label}
            </span>
          </div>
        </div>

        {/* Sub-route tabs / placeholders */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span
            className="dense-btn"
            style={{
              backgroundColor: "var(--surface-elevated)",
              color: "var(--semantic-blue)",
              borderColor: "var(--semantic-blue)",
              cursor: "default",
            }}
          >
            執行監控
          </span>
          <Link to={`/episodes/${id}/review`} className="dense-btn">
            審查波形
          </Link>
          <Link to={`/episodes/${id}/deliverables`} className="dense-btn">
            成品檔案
          </Link>
          <Link to={`/episodes/${id}/clips`} className="dense-btn">
            短片候選
          </Link>
        </div>
      </div>

      {isEpLoading && (
        <div
          style={{
            padding: "24px",
            textAlign: "center",
            color: "var(--text-muted)",
            fontFamily: "var(--font-mono)",
            fontSize: "var(--font-size-sm)",
          }}
        >
          載入集數資訊中...
        </div>
      )}

      {epError && (
        <div
          style={{
            padding: "12px",
            backgroundColor: "rgba(229, 72, 77, 0.1)",
            border: "1px solid rgba(229, 72, 77, 0.3)",
            borderRadius: "var(--radius-max)",
            color: "var(--semantic-red)",
            fontSize: "var(--font-size-sm)",
          }}
        >
          無法載入集數資訊: {(epError as Error).message}
        </div>
      )}

      {!isEpLoading && episode && (
        <>
          {reapplyCaption && (
            <div
              style={{
                padding: "8px 12px",
                border: "1px solid rgba(76, 141, 255, 0.3)",
                borderRadius: "var(--radius-max)",
                backgroundColor: "rgba(76, 141, 255, 0.1)",
                color: "var(--semantic-blue)",
                fontSize: "var(--font-size-sm)",
              }}
            >
              {reapplyCaption}
            </div>
          )}
          {/* Run Controls */}
          <RunControls
            profiles={profiles}
            isRunning={isRunning}
            onRun={handleRun}
            onCancel={handleCancel}
          />

          {/* Stage Grid */}
          <StageGrid parts={partsForGrid} stagesState={runState.stages} />

          {/* Log Tail Panel */}
          <LogPanel
            logs={runState.logs}
            isOpen={isLogOpen}
            onToggle={() => setIsLogOpen(!isLogOpen)}
            onClose={() => setIsLogOpen(false)}
          />

          {/* RUN_REPORT.md Renderer */}
          <RunReportView content={reportContent} />
        </>
      )}
    </div>
  );
};
