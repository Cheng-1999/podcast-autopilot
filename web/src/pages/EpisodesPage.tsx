import React, { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { deleteEpisode, fetchEpisodes } from "../api/client";
import { getStatusDisplay } from "../api/status";
import type { EpisodeSummary } from "../api/types";
import { useLocale } from "../i18n";
import { formatCount, formatDecimal, formatMinutesSeconds } from "../lib/format";

function formatDuration(seconds: number | null | undefined, locale: string): string {
  if (seconds === null || seconds === undefined || isNaN(seconds)) return "-";
  return formatMinutesSeconds(seconds, locale);
}

function formatLufs(lufs: number | null | undefined, locale: string): string {
  if (lufs === null || lufs === undefined || isNaN(lufs)) return "-";
  return `${formatDecimal(lufs, locale, 1)} LUFS`;
}

function formatTimestamp(ts: number | null | undefined, locale: string): string {
  if (!ts) return "-";
  const date = new Date(ts * 1000);
  return new Intl.DateTimeFormat(locale, { dateStyle: "short", timeStyle: "short" }).format(date);
}

export const EpisodesPage: React.FC = () => {
  const { t, locale } = useLocale();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const { data: episodes, isLoading, error } = useQuery<EpisodeSummary[]>({
    queryKey: ["episodes"],
    queryFn: fetchEpisodes,
    refetchInterval: 5000,
  });

  const handleDelete = async (ep: EpisodeSummary) => {
    if (!window.confirm(t("episodes.deleteConfirm", { title: ep.title || ep.id }))) return;
    setDeleteError(null);
    setDeletingId(ep.id);
    try {
      await deleteEpisode(ep.id);
      await queryClient.invalidateQueries({ queryKey: ["episodes"] });
    } catch (e) {
      setDeleteError((e as Error).message);
    } finally {
      setDeletingId(null);
    }
  };

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
            {t("episodes.heading")}
          </h1>
          <span className="mono" style={{ fontSize: "var(--font-size-xs)", color: "var(--text-muted)" }}>
            {t("episodes.count", { count: formatCount(episodes?.length ?? 0, locale) })}
          </span>
        </div>

        <div>
          <Link to="/episodes/new" className="dense-btn" data-tour="episodes-new">
            <span>{t("episodes.new")}</span>
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
          {t("common.loading")}
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
          {t("episodes.loadError", { message: (error as Error).message })}
        </div>
      )}

      {deleteError && (
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
          {t("episodes.deleteError", { message: deleteError })}
        </div>
      )}

      {/* Empty State */}
      {!isLoading && !error && episodes && episodes.length === 0 && (
        <div
          data-tour="episodes-list"
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
            {t("episodes.empty")}
          </div>
          <Link to="/episodes/new" className="dense-btn primary">
            {t("episodes.emptyAction")}
          </Link>
        </div>
      )}

      {/* Episodes Table */}
      {!isLoading && !error && episodes && episodes.length > 0 && (
        <div
          data-tour="episodes-list"
          style={{
            border: "var(--border-subtle)",
            borderRadius: "var(--radius-max)",
            backgroundColor: "var(--surface-panel)",
            padding: "8px 12px",
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
                  {t("episodes.columns.number")}
                </th>
                <th className="label-caps" style={{ padding: "0 12px", whiteSpace: "nowrap" }}>
                  {t("episodes.columns.title")}
                </th>
                <th className="label-caps" style={{ padding: "0 12px", width: "80px", whiteSpace: "nowrap" }}>
                  {t("episodes.columns.parts")}
                </th>
                <th className="label-caps" style={{ padding: "0 12px", width: "110px", whiteSpace: "nowrap" }}>
                  {t("episodes.columns.status")}
                </th>
                <th className="label-caps" style={{ padding: "0 12px", width: "150px", whiteSpace: "nowrap" }}>
                  {t("episodes.columns.lastRun")}
                </th>
                <th className="label-caps" style={{ padding: "0 12px", width: "90px", whiteSpace: "nowrap" }}>
                  {t("episodes.columns.duration")}
                </th>
                <th className="label-caps" style={{ padding: "0 12px", width: "100px", whiteSpace: "nowrap" }}>
                  LUFS
                </th>
                <th className="label-caps" style={{ padding: "0 12px", width: "80px", whiteSpace: "nowrap" }}>
                  {t("episodes.columns.actions")}
                </th>
              </tr>
            </thead>
            <tbody>
              {episodes.map((ep) => {
                const statusInfo = getStatusDisplay(ep.status, t);
                const epLabel =
                  ep.episode !== null && ep.episode !== undefined
                    ? `EP${ep.episode.toString().padStart(2, "0")}`
                    : ep.id;

                return (
                  <tr
                    key={ep.id}
                    data-testid={`episode-row-${ep.id}`}
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
                              fontSize: "11px",
                              padding: "3px 7px",
                              backgroundColor: "var(--surface-elevated)",
                              border: "var(--border-subtle)",
                              borderRadius: "var(--radius-max)",
                              color: "var(--text-muted)",
                            }}
                          >
                            {t("episode.example")}
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
                      {formatCount(ep.parts?.length ?? 0, locale)}
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
                      {formatTimestamp(ep.last_run_time, locale)}
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
                      {formatDuration(ep.duration, locale)}
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
                      {formatLufs(ep.lufs, locale)}
                    </td>

                    {/* Actions */}
                    <td style={{ padding: "0 12px", whiteSpace: "nowrap" }}>
                      <div style={{ display: "inline-flex", gap: "6px" }}>
                        <button
                          type="button"
                          className="dense-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            navigate(`/episodes/${ep.id}`);
                          }}
                        >
                          {t("common.open")}
                        </button>
                        {!ep.example && (
                          <button
                            type="button"
                            className="dense-btn danger"
                            disabled={deletingId === ep.id}
                            onClick={(e) => {
                              e.stopPropagation();
                              void handleDelete(ep);
                            }}
                          >
                            {deletingId === ep.id ? t("episodes.deleting") : t("episodes.delete")}
                          </button>
                        )}
                      </div>
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
