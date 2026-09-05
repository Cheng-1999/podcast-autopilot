import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { HealthResponse } from "../api/types";
import { LanguageSelector } from "./LanguageSelector";

interface StatusBarProps {
  health?: HealthResponse | null;
  activeJob?: {
    id: string;
    episodeId: string;
    status: string;
    startedAt?: number | null;
  } | null;
}

export const StatusBar: React.FC<StatusBarProps> = ({ health, activeJob }) => {
  const [elapsed, setElapsed] = useState<number>(0);

  useEffect(() => {
    if (!activeJob || activeJob.status !== "running" || !activeJob.startedAt) {
      setElapsed(0);
      return;
    }
    const update = () => {
      const now = Date.now() / 1000;
      setElapsed(Math.max(0, Math.floor(now - (activeJob.startedAt || now))));
    };
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [activeJob]);

  const ffmpegOk = health?.ffmpeg_ok ?? false;
  const models = health?.whisper_models || {};
  const modelSmallOk = models.small ?? false;
  const modelMedOk = models.medium ?? false;
  const cachedCount = (modelSmallOk ? 1 : 0) + (modelMedOk ? 1 : 0);
  const host = typeof window !== "undefined" ? window.location.host : "localhost:8765";

  return (
    <header
      style={{
        height: "var(--status-bar-height)",
        backgroundColor: "var(--surface-panel)",
        borderBottom: "var(--border-subtle)",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 12px",
        fontSize: "var(--font-size-sm)",
        userSelect: "none",
        zIndex: 10,
      }}
    >
      {/* Left side: Brand + Nav */}
      <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
        <Link
          to="/episodes"
          style={{
            fontWeight: 600,
            letterSpacing: "0.04em",
            color: "var(--text-primary)",
            display: "flex",
            alignItems: "center",
            gap: "6px",
          }}
        >
          <span className="mono" style={{ color: "var(--semantic-blue)" }}>
            AUTOPILOT
          </span>
          <span className="label-caps hide-on-mobile" style={{ color: "var(--text-muted)" }}>
            DASHBOARD
          </span>
        </Link>

        <nav style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <Link
            to="/episodes"
            style={{
              color: "var(--text-muted)",
              fontSize: "var(--font-size-xs)",
              display: "inline-flex",
              alignItems: "center",
            }}
          >
            集數
            <span className="kbd-hint hide-on-mobile">g e</span>
          </Link>
        </nav>
      </div>

      {/* Center: Active job monitor */}
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        {activeJob && activeJob.status === "running" ? (
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              padding: "2px 8px",
              backgroundColor: "var(--surface-elevated)",
              border: "1px solid rgba(76, 141, 255, 0.3)",
              borderRadius: "var(--radius-max)",
            }}
          >
            <span className="status-dot blue" />
            <span className="label-caps hide-on-mobile" style={{ color: "var(--semantic-blue)" }}>
              JOB:
            </span>
            <span className="mono" style={{ color: "var(--text-primary)" }}>
              {activeJob.episodeId}
            </span>
            <span className="mono" style={{ color: "var(--text-muted)" }}>
              +{elapsed}s
            </span>
          </div>
        ) : (
          <div style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
            <span className="status-dot muted" />
            <span className="mono" style={{ color: "var(--text-muted)", fontSize: "var(--font-size-xs)" }}>
              IDLE
            </span>
          </div>
        )}
      </div>

      {/* Right side: System health metrics */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "10px",
          color: "var(--text-muted)",
          fontSize: "var(--font-size-xs)",
        }}
      >
        {/* FFmpeg status */}
        <div style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
          <span className={`status-dot ${ffmpegOk ? "green" : "red"}`} />
          <span className="mono">ffmpeg {ffmpegOk ? "ok" : "err"}</span>
        </div>

        {/* Whisper models cached */}
        <div style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
          <span className={`status-dot ${cachedCount > 0 ? "green" : "amber"}`} />
          <span className="mono">models {cachedCount}/2</span>
        </div>

        {/* Free disk */}
        {health?.free_disk_gb !== undefined && health.free_disk_gb !== null && (
          <div className="hide-on-tablet" style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
            <span className="mono">{health.free_disk_gb.toFixed(0)}G</span>
          </div>
        )}

        {/* Host / LAN */}
        <div className="hide-on-mobile" style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
          <span className="mono" style={{ color: "var(--text-muted)" }}>
            LAN:{host}
          </span>
        </div>

        <LanguageSelector />
      </div>
    </header>
  );
};
