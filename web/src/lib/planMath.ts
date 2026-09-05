import type { PlanItem } from "../api/types";

/** Kinds that apply.py renders as an actual cut, mirroring audit.py's total_cut_duration. */
const REMOVAL_KINDS = new Set(["cut", "filler"]);

export function computeSecondsRemoved(items: Array<Pick<PlanItem, "kind" | "start" | "end" | "enabled">>): number {
  let total = 0;
  for (const it of items) {
    if (it.enabled && REMOVAL_KINDS.has(it.kind)) {
      total += it.end - it.start;
    }
  }
  return total;
}

export function computeEnabledFillerCount(items: Array<Pick<PlanItem, "kind" | "enabled">>): number {
  return items.filter((it) => it.kind === "filler" && it.enabled).length;
}

export interface SnippetRange {
  start: number;
  end: number;
}

export function computeSnippetRange(
  item: Pick<PlanItem, "start" | "end">,
  duration: number,
  pad = 1.5
): SnippetRange {
  const start = Math.max(0, item.start - pad);
  const rawEnd = item.end + pad;
  const end = duration > 0 ? Math.min(duration, rawEnd) : rawEnd;
  return { start, end };
}
