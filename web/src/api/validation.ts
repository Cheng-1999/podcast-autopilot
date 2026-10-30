export function parseTimestamp(value: string): number | null {
  const parts = value.trim().split(":").map(Number);
  if (parts.length < 2 || parts.length > 3 || parts.some((n) => !Number.isFinite(n) || n < 0)) return null;
  if (parts.some((n, i) => i > 0 && (n >= 60 || !Number.isInteger(n)))) return null;
  return parts.length === 3 ? parts[0] * 3600 + parts[1] * 60 + parts[2] : parts[0] * 60 + parts[1];
}
export type ChapterValidationError =
  | { key: "new.chapterTimeError"; params: { time: string } }
  | { key: "new.chapterExceedsDuration"; params: { title: string } };

export function validateChapters(chapters: Array<{ start: string; title: string }>, totalDuration: number): ChapterValidationError | null {
  for (const chapter of chapters) {
    const seconds = parseTimestamp(chapter.start);
    if (seconds === null) return { key: "new.chapterTimeError", params: { time: chapter.start } };
    if (seconds >= totalDuration) return { key: "new.chapterExceedsDuration", params: { title: chapter.title || chapter.start } };
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
