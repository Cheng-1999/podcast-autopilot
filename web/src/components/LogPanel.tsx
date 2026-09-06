import React, { useEffect, useRef, useState } from "react";
import { useLocale } from "../i18n";
import { formatCount } from "../lib/format";

interface LogPanelProps {
  logs: string[];
  isOpen: boolean;
  onToggle: () => void;
  onClose: () => void;
}

export const LogPanel: React.FC<LogPanelProps> = ({
  logs,
  isOpen,
  onToggle,
  onClose,
}) => {
  const { t, locale } = useLocale();
  const containerRef = useRef<HTMLDivElement>(null);
  const [isHovered, setIsHovered] = useState<boolean>(false);

  // Esc key listener
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  // Autoscroll when logs change and not hovered
  useEffect(() => {
    if (!isHovered && containerRef.current && isOpen) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [logs, isHovered, isOpen]);

  return (
    <div
      style={{
        border: "var(--border-subtle)",
        borderRadius: "var(--radius-max)",
        backgroundColor: "var(--surface-panel)",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* Header bar */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "6px 12px",
          backgroundColor: "var(--surface-elevated)",
          borderBottom: isOpen ? "var(--border-subtle)" : "none",
          cursor: "pointer",
          userSelect: "none",
        }}
        onClick={onToggle}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span className="label-caps">{t("log.heading")}</span>
          <span className="mono" style={{ fontSize: "var(--font-size-xs)", color: "var(--text-muted)" }}>
            {t("log.lines", { count: formatCount(logs.length, locale) })}
          </span>
          {isHovered && isOpen && (
            <span
              className="mono"
              style={{
                fontSize: "10px",
                padding: "1px 6px",
                backgroundColor: "var(--semantic-amber)",
                color: "#0F1216",
                borderRadius: "var(--radius-max)",
                fontWeight: 600,
              }}
            >
              {t("log.pause")}
            </span>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span className="mono" style={{ fontSize: "var(--font-size-xs)", color: "var(--text-muted)" }}>
            {isOpen ? t("log.collapse") : t("log.expand")}
          </span>
          <span className="kbd-hint">Esc</span>
        </div>
      </div>

      {/* Log tail body */}
      {isOpen && (
        <div
          ref={containerRef}
          onMouseEnter={() => setIsHovered(true)}
          onMouseLeave={() => setIsHovered(false)}
          style={{
            height: "180px",
            overflowY: "auto",
            padding: "8px 12px",
            backgroundColor: "#0F1216",
            fontFamily: "var(--font-mono)",
            fontSize: "12px",
            lineHeight: "1.5",
            color: "var(--text-primary)",
            whiteSpace: "pre-wrap",
            wordBreak: "break-all",
          }}
        >
          {logs.length === 0 ? (
            <div style={{ color: "var(--text-muted)" }}>{t("log.empty")}</div>
          ) : (
            logs.map((line, idx) => (
              <div
                key={idx}
                style={{
                  display: "flex",
                  gap: "10px",
                  borderBottom: "1px solid rgba(255,255,255,0.03)",
                }}
              >
                <span
                  style={{
                    color: "var(--text-muted)",
                    userSelect: "none",
                    width: "36px",
                    textAlign: "right",
                    flexShrink: 0,
                  }}
                >
                  {idx + 1}
                </span>
                <span style={{ flexGrow: 1 }}>{line}</span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
};
