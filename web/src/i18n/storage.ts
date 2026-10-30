import { DEFAULT_LOCALE, isLocale, type Locale } from "./types";

export const LOCALE_STORAGE_KEY = "autopilot.locale";

export function getStoredLocale(storage: Pick<Storage, "getItem"> = window.localStorage): Locale | null {
  try {
    const raw = storage.getItem(LOCALE_STORAGE_KEY);
    return isLocale(raw) ? raw : null;
  } catch {
    // localStorage can throw in private-browsing / disabled-storage modes.
    return null;
  }
}

export function setStoredLocale(locale: Locale, storage: Pick<Storage, "setItem"> = window.localStorage): void {
  try {
    storage.setItem(LOCALE_STORAGE_KEY, locale);
  } catch {
    // Persistence is best-effort; ignore quota / disabled-storage errors.
  }
}

function matchSingleLanguageTag(tag: string): Locale | null {
  const normalized = tag.trim();
  if (!normalized) return null;
  if (isLocale(normalized)) return normalized;

  const lower = normalized.toLowerCase();
  const primary = lower.split("-")[0];

  if (primary === "zh") {
    // Simplified-script or mainland/Singapore regions map to zh-CN; everything
    // else Chinese (Hant, TW, HK, MO, or a bare "zh") maps to zh-TW, matching
    // DEFAULT_LOCALE.
    if (lower.includes("hans") || lower.endsWith("-cn") || lower.endsWith("-sg")) {
      return "zh-CN";
    }
    return "zh-TW";
  }
  if (primary === "en") return "en";
  if (primary === "ja") return "ja";
  if (primary === "ko") return "ko";
  return null;
}

export function matchBrowserLocale(languages: readonly string[]): Locale | null {
  for (const tag of languages) {
    const match = matchSingleLanguageTag(tag);
    if (match) return match;
  }
  return null;
}

export function resolveInitialLocale(options?: {
  storage?: Pick<Storage, "getItem">;
  languages?: readonly string[];
}): Locale {
  const stored = getStoredLocale(options?.storage);
  if (stored) return stored;

  const languages =
    options?.languages ??
    (typeof navigator !== "undefined" ? navigator.languages ?? [navigator.language] : []);
  const matched = matchBrowserLocale(languages);
  if (matched) return matched;

  return DEFAULT_LOCALE;
}
