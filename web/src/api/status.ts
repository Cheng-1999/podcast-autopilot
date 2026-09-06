export type SemanticColor = "green" | "red" | "amber" | "blue" | "muted";

export interface StatusDisplay {
  label: string;
  color: SemanticColor;
  code: string;
}

import type { MessageKey } from "../i18n";
import { formatDecimal } from "../lib/format";

type Translate = (key: MessageKey, params?: Record<string, string | number>) => string;

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

const DEFAULT_STAGE_LABELS: Record<string, string> = {
  running: "running...",
  ran: "ran",
  cached: "cached",
  skipped: "skipped",
  failed: "failed",
  cancelled: "cancelled",
};

export function getStageDisplay(
  status: string | null | undefined,
  elapsed?: number | null,
  translate?: Translate,
  locale = "en"
): { label: string; color: SemanticColor } {
  const hasElapsed = elapsed !== undefined && elapsed !== null;
  const label = (key: MessageKey, fallback: string, params?: Record<string, string | number>) =>
    translate ? translate(key, params) : fallback;

  switch (status) {
    case "running":
      return { label: label("stage.status.running", DEFAULT_STAGE_LABELS.running), color: "blue" };
    case "ran":
      return {
        label: hasElapsed
          ? label("stage.status.ran", `ran ${formatDecimal(elapsed, locale, 1)}s`, { elapsed: formatDecimal(elapsed, locale, 1) })
          : label("stage.status.ranPlain", DEFAULT_STAGE_LABELS.ran),
        color: "green",
      };
    case "cached":
      return { label: label("stage.status.cached", DEFAULT_STAGE_LABELS.cached), color: "green" };
    case "skipped":
      return { label: label("stage.status.skipped", DEFAULT_STAGE_LABELS.skipped), color: "muted" };
    case "failed":
      return { label: label("stage.status.failed", DEFAULT_STAGE_LABELS.failed), color: "red" };
    case "cancelled":
      return { label: label("stage.status.cancelled", DEFAULT_STAGE_LABELS.cancelled), color: "amber" };
    case "pending":
    default:
      return { label: "-", color: "muted" };
  }
}
