import React from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchEpisode, fetchDeliverables, fetchReport, fetchJson } from "../api/client";
import type { EpisodeDetail, DeliverablesResponse, ReceiptData, ChapterEntry } from "../api/types";
import { RunReportView } from "../components/RunReportView";
import { formatTimeTenths } from "../lib/format";
import { useLocale } from "../i18n";

export const DeliverablesPage: React.FC = () => {
  const { id = "" } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t } = useLocale();

  const { data: episode } = useQuery<EpisodeDetail>({
    queryKey: ["episode", id],
    queryFn: () => fetchEpisode(id),
    enabled: Boolean(id),
  });

  const { data: deliverables, isLoading } = useQuery<DeliverablesResponse>({
    queryKey: ["deliverables", id],
    queryFn: () => fetchDeliverables(id),
    enabled: Boolean(id),
  });

  const { data: receipt } = useQuery<ReceiptData>({
    queryKey: ["receipt", deliverables?.receipt],
    queryFn: () => fetchJson<ReceiptData>(deliverables!.receipt!),
    enabled: Boolean(deliverables?.receipt),
  });

  const { data: chapters } = useQuery<ChapterEntry[]>({
    queryKey: ["chapters", deliverables?.chapters_json],
    queryFn: () => fetchJson<ChapterEntry[]>(deliverables!.chapters_json!),
    enabled: Boolean(deliverables?.chapters_json),
  });

  const { data: reportContent } = useQuery<string>({
    queryKey: ["report", id],
    queryFn: () => fetchReport(id),
    enabled: Boolean(id && episode?.report_available),
    retry: false,
  });

  const duration = receipt?.duration ?? episode?.duration ?? null;
  const lufs = receipt?.loudness.input_i ?? episode?.lufs ?? null;
  const truePeak = receipt?.loudness.input_tp ?? null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "10px",
          paddingBottom: "8px",
          borderBottom: "var(--border-subtle)",
        }}
      >
        <button type="button" className="dense-btn" onClick={() => navigate(`/episodes/${id}`)}>
          {t("nav.back")}
        </button>
        <h1 style={{ fontSize: "15px", fontWeight: 600, color: "var(--text-primary)" }}>
          {t("deliverables.heading")} — {episode?.title || id}
        </h1>
      </div>

      {isLoading && (
        <div style={{ padding: "24px", textAlign: "center", color: "var(--text-muted)" }}>{t("deliverables.loading")}</div>
      )}

      {deliverables && !deliverables.final_mp3 && (
        <div
          style={{
            padding: "16px",
            border: "var(--border-subtle)",
            borderRadius: "var(--radius-max)",
            backgroundColor: "var(--surface-panel)",
            color: "var(--text-muted)",
            textAlign: "center",
          }}
        >
          {t("deliverables.none")}
        </div>
      )}

      {deliverables?.final_mp3 && (
        <div
          style={{
            border: "var(--border-subtle)",
            borderRadius: "var(--radius-max)",
            backgroundColor: "var(--surface-panel)",
            padding: "16px",
            display: "flex",
            flexDirection: "column",
            gap: "10px",
          }}
        >
          <span className="label-caps">{t("deliverables.final")} (FINAL MP3)</span>
          <audio controls src={deliverables.final_mp3} style={{ width: "100%" }} />
          <div style={{ display: "flex", gap: "16px", fontSize: "var(--font-size-sm)", flexWrap: "wrap" }}>
            <span className="mono tabular-nums">時長: {duration !== null ? formatTimeTenths(duration) : "-"}</span>
            <span className="mono tabular-nums">LUFS: {lufs !== null ? lufs.toFixed(2) : "-"}</span>
            <span className="mono tabular-nums">True Peak: {truePeak !== null ? `${truePeak.toFixed(2)} dBTP` : "-"}</span>
            <a href={deliverables.final_mp3} download className="dense-btn">
              {t("deliverables.downloadMp3")}
            </a>
          </div>
        </div>
      )}

      {chapters && chapters.length > 0 && (
        <div
          style={{
            border: "var(--border-subtle)",
            borderRadius: "var(--radius-max)",
            backgroundColor: "var(--surface-panel)",
            overflow: "hidden",
          }}
        >
          <div style={{ padding: "8px 12px", borderBottom: "var(--border-subtle)", backgroundColor: "var(--surface-elevated)" }}>
            <span className="label-caps">{t("deliverables.chapters")} (CHAPTERS)</span>
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--font-size-sm)" }}>
            <thead>
              <tr style={{ height: "26px" }}>
                <th className="label-caps mono" style={{ padding: "0 12px", textAlign: "left" }}>
                  開始
                </th>
                <th className="label-caps" style={{ padding: "0 12px", textAlign: "left" }}>
                  標題
                </th>
              </tr>
            </thead>
            <tbody>
              {chapters.map((ch, i) => (
                <tr key={i} style={{ height: "var(--row-height)", borderTop: "var(--border-subtle)" }}>
                  <td className="mono tabular-nums" style={{ padding: "0 12px" }}>
                    {formatTimeTenths(ch.start)}
                  </td>
                  <td style={{ padding: "0 12px", color: "var(--text-primary)" }}>{ch.title}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {deliverables && deliverables.parts.length > 0 && (
        <div
          style={{
            border: "var(--border-subtle)",
            borderRadius: "var(--radius-max)",
            backgroundColor: "var(--surface-panel)",
            padding: "12px",
          }}
        >
          <div className="label-caps" style={{ marginBottom: "8px" }}>
            {t("deliverables.editedParts")} (EDITED PARTS)
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
            {deliverables.parts.map((p) => (
              <div key={p.part} style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <span className="mono" style={{ width: "140px", color: "var(--text-primary)" }}>
                  {p.part}
                </span>
                {p.edited_wav ? (
                  <a href={p.edited_wav} download className="dense-btn">
                    下載 WAV
                  </a>
                ) : (
                  <span style={{ color: "var(--text-muted)" }}>{t("deliverables.notProduced")}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <a href={`/api/episodes/${encodeURIComponent(id)}/report`} target="_blank" rel="noreferrer" className="dense-btn">
          {t("deliverables.openReport")}
        </a>
      </div>

      <RunReportView content={reportContent} />
    </div>
  );
};
