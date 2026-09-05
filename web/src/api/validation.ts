export function parseTimestamp(value: string): number | null {
  const parts = value.trim().split(":").map(Number);
  if (parts.length < 2 || parts.length > 3 || parts.some((n) => !Number.isFinite(n) || n < 0)) return null;
  if (parts.some((n, i) => i > 0 && (n >= 60 || !Number.isInteger(n)))) return null;
  return parts.length === 3 ? parts[0] * 3600 + parts[1] * 60 + parts[2] : parts[0] * 60 + parts[1];
}
export function validateChapters(chapters: Array<{ start: string; title: string }>, totalDuration: number): string | null {
  for (const chapter of chapters) {
    const seconds = parseTimestamp(chapter.start);
    if (seconds === null) return `章節時間格式錯誤：${chapter.start}`;
    if (seconds >= totalDuration) return `章節「${chapter.title || chapter.start}」超過音檔總長度`;
  }
  return null;
}

export function reorder<T>(items: T[], index: number, direction: -1 | 1): T[] {
  const target = index + direction;
  if (index < 0 || index >= items.length || target < 0 || target >= items.length) return items;
  const next = [...items];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}
