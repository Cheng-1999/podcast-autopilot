export type SemanticColor = "green" | "red" | "amber" | "blue" | "muted";

export interface StatusDisplay {
  label: string;
  color: SemanticColor;
  code: string;
}

export function getStatusDisplay(status: string | null | undefined): StatusDisplay {
  switch (status) {
    case "done":
      return { label: "已完成", color: "green", code: "done" };
    case "needs-review":
      return { label: "待審查", color: "amber", code: "needs-review" };
    case "running":
      return { label: "執行中", color: "blue", code: "running" };
    case "never-run":
      return { label: "未執行", color: "muted", code: "never-run" };
    case "failed":
      return { label: "失敗", color: "red", code: "failed" };
    case "invalid":
      return { label: "無效配置", color: "red", code: "invalid" };
    default:
      return { label: status || "未知", color: "muted", code: status || "unknown" };
  }
}

export function getStageDisplay(
  status: string | null | undefined,
  elapsed?: number | null
): { label: string; color: SemanticColor } {
  switch (status) {
    case "running":
      return { label: "running...", color: "blue" };
    case "ran":
      return {
        label: elapsed !== undefined && elapsed !== null ? `ran ${elapsed.toFixed(1)}s` : "ran",
        color: "green",
      };
    case "cached":
      return { label: "cached", color: "green" };
    case "skipped":
      return { label: "skipped", color: "muted" };
    case "failed":
      return { label: "failed", color: "red" };
    case "cancelled":
      return { label: "cancelled", color: "amber" };
    case "pending":
    default:
      return { label: "-", color: "muted" };
  }
}
