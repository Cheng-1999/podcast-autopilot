const PAD2: Intl.NumberFormatOptions = { minimumIntegerDigits: 2, useGrouping: false };

export function formatTimeTenths(seconds: number, locale = "en"): string {
  const safe = Number.isFinite(seconds) && seconds > 0 ? seconds : 0;
  const mm = Math.floor(safe / 60);
  const ss = safe - mm * 60;
  const mmFmt = new Intl.NumberFormat(locale, PAD2).format(mm);
  const ssFmt = new Intl.NumberFormat(locale, { ...PAD2, minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(ss);
  return `${mmFmt}:${ssFmt}`;
}

export function formatTimeShort(seconds: number, locale = "en"): string {
  const safe = Number.isFinite(seconds) && seconds > 0 ? seconds : 0;
  const mm = Math.floor(safe / 60);
  const ss = Math.floor(safe - mm * 60);
  return `${new Intl.NumberFormat(locale, PAD2).format(mm)}:${new Intl.NumberFormat(locale, PAD2).format(ss)}`;
}

export function formatMinutesSeconds(totalSeconds: number, locale = "en"): string {
  const safe = Number.isFinite(totalSeconds) && totalSeconds > 0 ? totalSeconds : 0;
  const mm = Math.floor(safe / 60);
  const ss = Math.floor(safe % 60);
  return `${new Intl.NumberFormat(locale, { useGrouping: false }).format(mm)}:${new Intl.NumberFormat(locale, PAD2).format(ss)}`;
}

export function formatCount(value: number, locale = "en"): string {
  return new Intl.NumberFormat(locale).format(value);
}

export function formatDecimal(value: number, locale = "en", digits = 1): string {
  return new Intl.NumberFormat(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}
