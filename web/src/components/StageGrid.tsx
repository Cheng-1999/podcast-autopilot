import React, { useEffect, useRef, useState } from "react";
import { ALL_PART_STAGES, type PartStagesMap, type StageInfo } from "../api/sse";
import { getStageDisplay } from "../api/status";
import { useLocale } from "../i18n";

interface StageGridProps {
  parts: Array<{ stem: string }>;
  stagesState: Record<string, PartStagesMap>;
}

export const StageGrid: React.FC<StageGridProps> = ({ parts, stagesState }) => {
  const { t } = useLocale();
  const prevStagesRef = useRef<Record<string, string>>({});
  const [flashingKeys, setFlashingKeys] = useState<Record<string, boolean>>({});

  useEffect(() => {
    const nextFlashing: Record<string, boolean> = {};
    let changed = false;

    // Check all part stages
    for (const p of parts) {
      const partStages = stagesState[p.stem] || {};
      for (const stage of ALL_PART_STAGES) {
        const key = `${p.stem}:${stage}`;
        const current = partStages[stage];
        const stateKey = `${current?.status}:${current?.elapsed}`;
        if (prevStagesRef.current[key] && prevStagesRef.current[key] !== stateKey) {
          nextFlashing[key] = true;
          changed = true;
        }
        prevStagesRef.current[key] = stateKey;
      }
    }

    // Check assemble
    const assembleStage = stagesState["__assemble__"]?.assemble;
    const assembleKey = `__assemble__:assemble`;
    const assembleStateKey = `${assembleStage?.status}:${assembleStage?.elapsed}`;
    if (
      prevStagesRef.current[assembleKey] &&
      prevStagesRef.current[assembleKey] !== assembleStateKey
    ) {
      nextFlashing[assembleKey] = true;
      changed = true;
    }
    prevStagesRef.current[assembleKey] = assembleStateKey;

    if (changed) {
      setFlashingKeys((prev) => ({ ...prev, ...nextFlashing }));
      const timer = setTimeout(() => {
        setFlashingKeys({});
      }, 120);
      return () => clearTimeout(timer);
    }
  }, [parts, stagesState]);

  const renderCell = (stageInfo?: StageInfo, cellKey?: string) => {
    const isFlashing = cellKey ? flashingKeys[cellKey] : false;
    const display = getStageDisplay(stageInfo?.status, stageInfo?.elapsed, t);

    return (
      <td
        className={isFlashing ? "flash-pulse" : ""}
        style={{
          height: "var(--row-height)",
          padding: "0 8px",
          borderBottom: "var(--border-subtle)",
          borderRight: "var(--border-subtle)",
          whiteSpace: "nowrap",
          fontSize: "var(--font-size-xs)",
        }}
      >
        <div style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
          <span className={`status-dot ${display.color}`} />
          <span
            className="mono"
            style={{
              color:
                display.color === "green"
                  ? "var(--semantic-green)"
                  : display.color === "blue"
                  ? "var(--semantic-blue)"
                  : display.color === "red"
                  ? "var(--semantic-red)"
                  : display.color === "amber"
                  ? "var(--semantic-amber)"
                  : "var(--text-muted)",
            }}
          >
            {display.label}
          </span>
        </div>
      </td>
    );
  };

  const assembleStage = stagesState["__assemble__"]?.assemble;

  return (
    <div
      style={{
        border: "var(--border-subtle)",
        borderRadius: "var(--radius-max)",
        backgroundColor: "var(--surface-panel)",
        overflowX: "auto",
      }}
    >
      <div
        style={{
          padding: "8px 12px",
          borderBottom: "var(--border-subtle)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span className="label-caps">{t("stage.heading")}</span>
          <span className="mono" style={{ fontSize: "var(--font-size-xs)", color: "var(--text-muted)" }}>
            {t("status.live")}
          </span>
        </div>
      </div>

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
            <th
              className="label-caps"
              style={{
                padding: "0 10px",
                borderRight: "var(--border-subtle)",
                width: "140px",
              }}
            >
              {t("stage.part")}
            </th>
            {ALL_PART_STAGES.map((stage) => (
              <th
                key={stage}
                className="label-caps mono"
                style={{
                  padding: "0 8px",
                  borderRight: "var(--border-subtle)",
                  fontSize: "var(--font-size-xs)",
                }}
              >
                {stage}
              </th>
            ))}
            <th
              className="label-caps mono"
              style={{
                padding: "0 8px",
                fontSize: "var(--font-size-xs)",
              }}
            >
              assemble
            </th>
          </tr>
        </thead>
        <tbody>
          {parts.map((p) => {
            const partStages = stagesState[p.stem] || {};
            return (
              <tr key={p.stem} style={{ height: "var(--row-height)" }}>
                <td
                  className="mono"
                  style={{
                    padding: "0 10px",
                    fontWeight: 500,
                    borderBottom: "var(--border-subtle)",
                    borderRight: "var(--border-subtle)",
                    color: "var(--text-primary)",
                  }}
                >
                  {p.stem}
                </td>
                {ALL_PART_STAGES.map((stage) => {
                  const stageInfo = partStages[stage];
                  const cellKey = `${p.stem}:${stage}`;
                  return (
                    <React.Fragment key={stage}>
                      {renderCell(stageInfo, cellKey)}
                    </React.Fragment>
                  );
                })}
                <td
                  style={{
                    padding: "0 8px",
                    borderBottom: "var(--border-subtle)",
                    color: "var(--text-muted)",
                    fontSize: "var(--font-size-xs)",
                  }}
                >
                  <span className="mono">-</span>
                </td>
              </tr>
            );
          })}

          {/* Episode assembly row */}
          <tr
            style={{
              height: "var(--row-height)",
              backgroundColor: "var(--surface-elevated)",
            }}
          >
            <td
              className="mono"
              style={{
                padding: "0 10px",
                fontWeight: 600,
                borderRight: "var(--border-subtle)",
                color: "var(--text-primary)",
              }}
            >
              {t("stage.assembly")}
            </td>
            {ALL_PART_STAGES.map((stage) => (
              <td
                key={stage}
                style={{
                  padding: "0 8px",
                  borderRight: "var(--border-subtle)",
                  color: "var(--text-muted)",
                  fontSize: "var(--font-size-xs)",
                }}
              >
                <span className="mono">-</span>
              </td>
            ))}
            {renderCell(assembleStage, "__assemble__:assemble")}
          </tr>
        </tbody>
      </table>
    </div>
  );
};
