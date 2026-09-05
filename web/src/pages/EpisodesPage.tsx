import React from "react";
import { useNavigate, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchEpisodes } from "../api/client";
import { getStatusDisplay } from "../api/status";
import type { EpisodeSummary } from "../api/types";

function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || isNaN(seconds)) return "-";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function formatLufs(lufs: number | null | undefined): string {
  if (lufs === null || lufs === undefined || isNaN(lufs)) return "-";
  return `${lufs.toFixed(1)} LUFS`;
}

function formatTimestamp(ts: number | null | undefined): string {
  if (!ts) return "-";
  const date = new Date(ts * 1000);
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours()
  )}:${pad(date.getMinutes())}`;
}

export const EpisodesPage: React.FC = () => {
  const navigate = useNavigate();
  const { data: episodes, isLoading, error } = useQuery<EpisodeSummary[]>({
    queryKey: ["episodes"],
    queryFn: fetchEpisodes,
    refetchInterval: 5000,
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      {/* Header bar */}
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
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <h1 style={{ fontSize: "16px", fontWeight: 600, color: "var(--text-primary)" }}>
            集數清單 (EPISODES)
          </h1>
          <span className="mono" style={{ fontSize: "var(--font-size-xs)", color: "var(--text-muted)" }}>
            共 {episodes?.length ?? 0} 集
          </span>
        </div>

        <div>
          <Link to="/episodes/new" className="dense-btn">
            <span>+ 新增集數</span>
          </Link>
        </div>
      </div>

      {/* Loading & Error States */}
      {isLoading && (
        <div
          style={{
            padding: "24px",
            textAlign: "center",
            color: "var(--text-muted)",
            fontFamily: "var(--font-mono)",
            fontSize: "var(--font-size-sm)",
          }}
        >
          載入中...
        </div>
      )}

      {error && (
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
          無法載入集數清單: {(error as Error).message}
        </div>
      )}

      {/* Empty State */}
      {!isLoading && !error && episodes && episodes.length === 0 && (
        <div
          style={{
            padding: "32px 16px",
            textAlign: "center",
            backgroundColor: "var(--surface-panel)",
            border: "var(--border-subtle)",
            borderRadius: "var(--radius-max)",
            color: "var(--text-muted)",
          }}
        >
          <div style={{ marginBottom: "12px", fontSize: "var(--font-size-base)" }}>
            尚無任何集數檔案
          </div>
          <Link to="/episodes/new" className="dense-btn primary">
            前往新增集數向導精靈
          </Link>
        </div>
      )}

      {/* Episodes Table */}
      {!isLoading && !error && episodes && episodes.length > 0 && (
        <div
          style={{
            border: "var(--border-subtle)",
            borderRadius: "var(--radius-max)",
            backgroundColor: "var(--surface-panel)",
            overflowX: "auto",
          }}
        >
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              textAlign: "left",
              fontSize: "var(--font-size-sm)",
            }}
          >
            <thead>
              <tr
                style={{
                  backgroundColor: "var(--surface-elevated)",
                  borderBottom: "var(--border-subtle)",
                  height: "28px",
                }}
              >
                <th className="label-caps" style={{ padding: "0 12px", width: "70px", whiteSpace: "nowrap" }}>
                  集數
                </th>
                <th className="label-caps" style={{ padding: "0 12px", whiteSpace: "nowrap" }}>
                  標題 (TITLE)
                </th>
                <th className="label-caps" style={{ padding: "0 12px", width: "80px", whiteSpace: "nowrap" }}>
                  段落數
                </th>
                <th className="label-caps" style={{ padding: "0 12px", width: "110px", whiteSpace: "nowrap" }}>
                  狀態 (STATUS)
                </th>
                <th className="label-caps" style={{ padding: "0 12px", width: "150px", whiteSpace: "nowrap" }}>
                  上次執行
                </th>
                <th className="label-caps" style={{ padding: "0 12px", width: "90px", whiteSpace: "nowrap" }}>
                  時長
                </th>
                <th className="label-caps" style={{ padding: "0 12px", width: "100px", whiteSpace: "nowrap" }}>
                  LUFS
                </th>
                <th className="label-caps" style={{ padding: "0 12px", width: "80px", whiteSpace: "nowrap" }}>
                  操作
                </th>
              </tr>
            </thead>
            <tbody>
              {episodes.map((ep) => {
                const statusInfo = getStatusDisplay(ep.status);
                const epLabel =
                  ep.episode !== null && ep.episode !== undefined
                    ? `EP${ep.episode.toString().padStart(2, "0")}`
                    : ep.id;

                return (
                  <tr
                    key={ep.id}
                    onClick={() => navigate(`/episodes/${ep.id}`)}
                    style={{
                      height: "var(--row-height)",
                      borderBottom: "var(--border-subtle)",
                      cursor: "pointer",
                      transition: "background-color 80ms ease",
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.backgroundColor = "var(--surface-hover)";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.backgroundColor = "transparent";
                    }}
                  >
                    {/* Episode No. */}
                    <td
                      className="mono"
                      style={{
                        padding: "0 12px",
                        fontWeight: 600,
                        color: "var(--text-primary)",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {epLabel}
                    </td>

                    {/* Title */}
                    <td
                      style={{
                        padding: "0 12px",
                        color: "var(--text-primary)",
                        fontWeight: 500,
                        whiteSpace: "nowrap",
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                        <span>{ep.title || ep.id}</span>
                        {ep.example && (
                          <span
                            className="mono"
                            style={{
                              fontSize: "10px",
                              padding: "1px 4px",
                              backgroundColor: "var(--surface-elevated)",
                              border: "var(--border-subtle)",
                              borderRadius: "var(--radius-max)",
                              color: "var(--text-muted)",
                            }}
                          >
                            EXAMPLE
                          </span>
                        )}
                      </div>
                    </td>

                    {/* Parts count */}
                    <td
                      className="mono"
                      style={{
                        padding: "0 12px",
                        color: "var(--text-muted)",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {ep.parts?.length ?? 0}
                    </td>

                    {/* Status word colored semantically */}
                    <td style={{ padding: "0 12px", whiteSpace: "nowrap" }}>
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
                            fontWeight: 500,
                          }}
                        >
                          {statusInfo.label}
                        </span>
                      </div>
                    </td>

                    {/* Last run */}
                    <td
                      className="mono"
                      style={{
                        padding: "0 12px",
                        color: "var(--text-muted)",
                        fontSize: "var(--font-size-xs)",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {formatTimestamp(ep.last_run_time)}
                    </td>

                    {/* Duration */}
                    <td
                      className="mono"
                      style={{
                        padding: "0 12px",
                        color: "var(--text-primary)",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {formatDuration(ep.duration)}
                    </td>

                    {/* LUFS */}
                    <td
                      className="mono"
                      style={{
                        padding: "0 12px",
                        color: "var(--text-muted)",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {formatLufs(ep.lufs)}
                    </td>

                    {/* Actions */}
                    <td style={{ padding: "0 12px", whiteSpace: "nowrap" }}>
                      <button
                        type="button"
                        className="dense-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          navigate(`/episodes/${ep.id}`);
                        }}
                      >
                        開啟
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
