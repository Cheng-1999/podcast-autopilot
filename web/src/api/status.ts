export type SemanticColor = "green" | "red" | "amber" | "blue" | "muted";

export interface StatusDisplay {
  label: string;
  color: SemanticColor;
  code: string;
}

import type { MessageKey } from "../i18n";

type Translate = (key: MessageKey) => string;

const STATUS_KEYS: Record<string, MessageKey> = {
  done: "status.done",
  "needs-review": "status.needsReview",
  running: "status.running",
  "never-run": "status.neverRun",
  failed: "status.failed",
  invalid: "status.invalid",
};

const DEFAULT_LABELS: Record<string, string> = {
  done: "已完成",
  "needs-review": "待審查",
  running: "執行中",
  "never-run": "未執行",
  failed: "失敗",
  invalid: "無效配置",
};

export function getStatusDisplay(status: string | null | undefined, translate?: Translate): StatusDisplay {
  const code = status || "unknown";
  const key = STATUS_KEYS[code];
  const label = translate ? (key ? translate(key) : translate("status.unknown")) : (DEFAULT_LABELS[code] || "未知");
  switch (status) {
    case "done":
      return { label, color: "green", code: "done" };
    case "needs-review":
      return { label, color: "amber", code: "needs-review" };
    case "running":
      return { label, color: "blue", code: "running" };
    case "never-run":
      return { label, color: "muted", code: "never-run" };
    case "failed":
      return { label, color: "red", code: "failed" };
    case "invalid":
      return { label, color: "red", code: "invalid" };
    default:
      return { label: status || label, color: "muted", code };
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
