export function formatTimeTenths(seconds: number): string {
  const safe = Number.isFinite(seconds) && seconds > 0 ? seconds : 0;
  const mm = Math.floor(safe / 60);
  const ss = safe - mm * 60;
  return `${String(mm).padStart(2, "0")}:${ss.toFixed(1).padStart(4, "0")}`;
}

export function formatTimeShort(seconds: number): string {
  const safe = Number.isFinite(seconds) && seconds > 0 ? seconds : 0;
  const mm = Math.floor(safe / 60);
  const ss = Math.floor(safe - mm * 60);
  return `${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}
