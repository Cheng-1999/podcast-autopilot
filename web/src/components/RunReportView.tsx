import React, { useMemo } from "react";
import { marked } from "marked";
import { useLocale } from "../i18n";

interface RunReportViewProps {
  content: string | null | undefined;
}

export const RunReportView: React.FC<RunReportViewProps> = ({ content }) => {
  const { t } = useLocale();
  const html = useMemo(() => {
    if (!content) return "";
    try {
      return marked.parse(content, { gfm: true, breaks: true }) as string;
    } catch {
      return content;
    }
  }, [content]);

  if (!content) {
    return (
      <div
        style={{
          border: "var(--border-subtle)",
          borderRadius: "var(--radius-max)",
          backgroundColor: "var(--surface-panel)",
          padding: "16px",
          color: "var(--text-muted)",
          fontSize: "var(--font-size-sm)",
          textAlign: "center",
        }}
      >
        {t("report.empty")}
      </div>
    );
  }

  return (
    <div
      style={{
        border: "var(--border-subtle)",
        borderRadius: "var(--radius-max)",
        backgroundColor: "var(--surface-panel)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "8px 12px",
          borderBottom: "var(--border-subtle)",
          backgroundColor: "var(--surface-elevated)",
          display: "flex",
          alignItems: "center",
          gap: "8px",
        }}
      >
        <span className="label-caps">{t("report.heading")} (RUN_REPORT.md)</span>
      </div>

      <div
        className="run-report-container"
        dangerouslySetInnerHTML={{ __html: html }}
        style={{
          padding: "16px",
          fontSize: "var(--font-size-sm)",
          lineHeight: "1.6",
          color: "var(--text-primary)",
          overflowX: "auto",
        }}
      />

      <style>{`
        .run-report-container h1,
        .run-report-container h2,
        .run-report-container h3,
        .run-report-container h4 {
          margin-top: 16px;
          margin-bottom: 8px;
          font-weight: 600;
          color: var(--text-primary);
        }
        .run-report-container h1 { font-size: 19px; border-bottom: var(--border-subtle); padding-bottom: 4px; }
        .run-report-container h2 { font-size: 14px; color: var(--semantic-blue); }
        .run-report-container h3 { font-size: 13px; }
        .run-report-container p,
        .run-report-container ul,
        .run-report-container ol {
          margin-bottom: 10px;
          max-width: 65ch;
        }
        .run-report-container ul,
        .run-report-container ol {
          padding-left: 20px;
        }
        .run-report-container table {
          width: 100%;
          border-collapse: collapse;
          margin: 12px 0;
          font-family: var(--font-mono);
          font-size: 12px;
        }
        .run-report-container th,
        .run-report-container td {
          border: var(--border-subtle);
          padding: 6px 10px;
          text-align: left;
        }
        .run-report-container th {
          background-color: var(--surface-elevated);
          color: var(--text-muted);
          font-size: 11px;
          text-transform: uppercase;
          letter-spacing: 0.06em;
        }
        .run-report-container code {
          font-family: var(--font-mono);
          font-size: 12px;
          background-color: var(--surface-elevated);
          padding: 2px 4px;
          border-radius: var(--radius-max);
          border: var(--border-subtle);
          overflow-wrap: anywhere;
        }
        .run-report-container pre {
          background-color: #0F1216;
          border: var(--border-subtle);
          border-radius: var(--radius-max);
          padding: 10px 12px;
          overflow-x: auto;
          margin: 10px 0;
          white-space: pre-wrap;
          word-break: break-word;
        }
        .run-report-container pre code {
          background-color: transparent;
          padding: 0;
          border: none;
        }
      `}</style>
    </div>
  );
};
