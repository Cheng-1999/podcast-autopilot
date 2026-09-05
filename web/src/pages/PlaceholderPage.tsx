import React from "react";
import { useParams, Link } from "react-router-dom";

interface PlaceholderPageProps {
  type: "review" | "deliverables" | "wizard";
}

export const PlaceholderPage: React.FC<PlaceholderPageProps> = ({ type }) => {
  const { id } = useParams<{ id: string }>();

  let title = "";
  let description = "";

  if (type === "review") {
    title = `集數審查 (REVIEW) - ${id}`;
    description = "波形檢視、編輯計畫核取方塊切換、片段試聽與重新套用功能將於後續任務實作。";
  } else if (type === "deliverables") {
    title = `成品檔案 (DELIVERABLES) - ${id}`;
    description = "MP3、SRT 字幕、章節標記與社群短影音候選片段檢視功能將於後續任務實作。";
  } else {
    title = "新增集數向導 (NEW EPISODE WIZARD)";
    description = "新集數建立與音檔上傳向導將於後續任務實作。";
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "16px",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          paddingBottom: "8px",
          borderBottom: "var(--border-subtle)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          {id ? (
            <Link to={`/episodes/${id}`} className="dense-btn">
              ← 返回集數
            </Link>
          ) : (
            <Link to="/episodes" className="dense-btn">
              ← 返回列表
            </Link>
          )}
          <h1 style={{ fontSize: "15px", fontWeight: 600, color: "var(--text-primary)" }}>
            {title}
          </h1>
        </div>
      </div>

      <div
        style={{
          border: "var(--border-subtle)",
          borderRadius: "var(--radius-max)",
          backgroundColor: "var(--surface-panel)",
          padding: "32px 20px",
          textAlign: "center",
          color: "var(--text-muted)",
        }}
      >
        <div className="mono" style={{ fontSize: "14px", color: "var(--semantic-blue)", marginBottom: "8px" }}>
          [佔位頁面 - 施工中]
        </div>
        <p style={{ fontSize: "var(--font-size-base)", color: "var(--text-primary)" }}>
          {description}
        </p>
      </div>
    </div>
  );
};
