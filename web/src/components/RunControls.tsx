import React, { useState } from "react";
import { ALL_PIPELINE_STAGES } from "../api/sse";

interface RunControlsProps {
  profiles: string[];
  isRunning: boolean;
  onRun: (options: { profile: string; model: string; force: boolean; skip: string[] }) => void;
  onCancel: () => void;
}

export const RunControls: React.FC<RunControlsProps> = ({
  profiles,
  isRunning,
  onRun,
  onCancel,
}) => {
  const [profile, setProfile] = useState<string>("default");
  const [model, setModel] = useState<string>("medium");
  const [force, setForce] = useState<boolean>(false);
  const [skipStages, setSkipStages] = useState<string[]>([]);
  const [showSkipDropdown, setShowSkipDropdown] = useState<boolean>(false);

  const toggleSkipStage = (stage: string) => {
    setSkipStages((prev) =>
      prev.includes(stage) ? prev.filter((s) => s !== stage) : [...prev, stage]
    );
  };

  const handleRun = () => {
    if (isRunning) return;
    onRun({ profile, model, force, skip: skipStages });
  };

  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "12px",
        padding: "10px 14px",
        backgroundColor: "var(--surface-panel)",
        border: "var(--border-subtle)",
        borderRadius: "var(--radius-max)",
      }}
    >
      {/* Configuration Controls */}
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "14px" }}>
        {/* Profile */}
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <label className="label-caps" htmlFor="profile-select">
            配置檔 (PROFILE):
          </label>
          <select
            id="profile-select"
            className="dense-select"
            value={profile}
            onChange={(e) => setProfile(e.target.value)}
            disabled={isRunning}
          >
            {profiles.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>

        {/* Model */}
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <label className="label-caps" htmlFor="model-select">
            模型 (MODEL):
          </label>
          <select
            id="model-select"
            className="dense-select"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            disabled={isRunning}
          >
            <option value="small">small (快速)</option>
            <option value="medium">medium (高精度)</option>
          </select>
        </div>

        {/* Force Checkbox */}
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <input
            id="force-check"
            type="checkbox"
            checked={force}
            onChange={(e) => setForce(e.target.checked)}
            disabled={isRunning}
            style={{
              accentColor: "var(--semantic-blue)",
              cursor: isRunning ? "not-allowed" : "pointer",
            }}
          />
          <label
            htmlFor="force-check"
            className="mono"
            style={{
              fontSize: "var(--font-size-xs)",
              color: "var(--text-primary)",
              cursor: isRunning ? "not-allowed" : "pointer",
            }}
          >
            強制重新執行 (force)
          </label>
        </div>

        {/* Skip Multi-select */}
        <div style={{ position: "relative" }}>
          <button
            type="button"
            className="dense-btn"
            onClick={() => setShowSkipDropdown(!showSkipDropdown)}
            disabled={isRunning}
          >
            <span className="label-caps">略過階段 (SKIP):</span>
            <span className="mono" style={{ color: "var(--semantic-blue)" }}>
              {skipStages.length > 0 ? `${skipStages.length} 個階段` : "無"}
            </span>
          </button>

          {showSkipDropdown && (
            <div
              style={{
                position: "absolute",
                top: "100%",
                left: 0,
                marginTop: "4px",
                backgroundColor: "var(--surface-elevated)",
                border: "var(--border-subtle)",
                borderRadius: "var(--radius-max)",
                padding: "6px 8px",
                zIndex: 20,
                boxShadow: "none",
                display: "flex",
                flexDirection: "column",
                gap: "4px",
                minWidth: "160px",
              }}
            >
              {ALL_PIPELINE_STAGES.map((stage) => {
                const checked = skipStages.includes(stage);
                return (
                  <label
                    key={stage}
                    className="mono"
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "6px",
                      fontSize: "var(--font-size-xs)",
                      cursor: "pointer",
                      padding: "2px 4px",
                      color: checked ? "var(--text-primary)" : "var(--text-muted)",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleSkipStage(stage)}
                      style={{ accentColor: "var(--semantic-blue)" }}
                    />
                    {stage}
                  </label>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Action Buttons with keyboard hints */}
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <button
          type="button"
          className="dense-btn primary"
          onClick={handleRun}
          disabled={isRunning}
        >
          <span>開始執行</span>
          <span className="kbd-hint" style={{ color: "#0F1216", backgroundColor: "rgba(0,0,0,0.15)" }}>
            r
          </span>
        </button>

        <button
          type="button"
          className="dense-btn danger"
          onClick={onCancel}
          disabled={!isRunning}
        >
          <span>取消執行</span>
        </button>
      </div>
    </div>
  );
};
