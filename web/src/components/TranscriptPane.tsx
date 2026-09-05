import React, { useMemo, useRef, useState } from "react";
import type { TranscriptSegment } from "../api/types";
import { formatTimeShort } from "../lib/format";
import { useLocale } from "../i18n";

interface TranscriptPaneProps {
  segments: TranscriptSegment[];
  currentTime: number;
  onSeek: (time: number) => void;
}

export const TranscriptPane: React.FC<TranscriptPaneProps> = ({ segments, currentTime, onSeek }) => {
  const { t } = useLocale();
  const [query, setQuery] = useState("");
  const activeRef = useRef<HTMLDivElement | null>(null);

  const filtered = useMemo(() => {
    if (!query.trim()) return segments;
    const q = query.trim().toLowerCase();
    return segments.filter((s) => s.text.toLowerCase().includes(q));
  }, [segments, query]);

  const activeId = useMemo(() => {
    const hit = segments.find((s) => currentTime >= s.start && currentTime < s.end);
    return hit?.id ?? null;
  }, [segments, currentTime]);

  return (
    <div
      style={{
        border: "var(--border-subtle)",
        borderRadius: "var(--radius-max)",
        backgroundColor: "var(--surface-panel)",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        height: "100%",
      }}
    >
      <div
        style={{
          padding: "8px 12px",
          borderBottom: "var(--border-subtle)",
          backgroundColor: "var(--surface-elevated)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "8px",
        }}
      >
        <span className="label-caps">{t("transcript.heading")} (TRANSCRIPT)</span>
        <input
          type="text"
          className="dense-input"
          placeholder={t("transcript.search")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ width: "140px" }}
        />
      </div>
      <div style={{ overflowY: "auto", flex: 1, padding: "8px 0" }}>
        {filtered.map((seg) => {
          const active = seg.id === activeId;
          return (
            <div
              key={seg.id}
              ref={active ? activeRef : undefined}
              onClick={() => onSeek(seg.start)}
              style={{
                padding: "4px 12px",
                cursor: "pointer",
                backgroundColor: active ? "var(--surface-active)" : "transparent",
                display: "flex",
                gap: "8px",
                fontSize: "var(--font-size-sm)",
              }}
            >
              <span className="mono tabular-nums" style={{ color: "var(--text-muted)", flexShrink: 0 }}>
                [{formatTimeShort(seg.start)}]
              </span>
              <span style={{ color: active ? "var(--text-primary)" : "var(--text-muted)" }}>{seg.text}</span>
            </div>
          );
        })}
        {filtered.length === 0 && (
          <div style={{ padding: "16px", textAlign: "center", color: "var(--text-muted)" }}>{t("transcript.noResults")}</div>
        )}
      </div>
    </div>
  );
};
