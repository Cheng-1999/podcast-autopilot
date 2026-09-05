import type { Locale } from "../types";
import en, { type MessageKey } from "./en";
import zhTW from "./zh-TW";
import zhCN from "./zh-CN";
import ja from "./ja";
import ko from "./ko";

export type { MessageKey };

// Catalogs are complete; the resolver retains an English fallback for
// forward compatibility when a new key is introduced.
export const catalogs: Record<Locale, Record<MessageKey, string>> = {
  en,
  "zh-TW": zhTW,
  "zh-CN": zhCN,
  ja,
  ko,
};

export function resolveMessage<K extends string>(
  key: K,
  catalog: Partial<Record<K, string>>,
  fallbackCatalog: Record<K, string>
): string {
  return catalog[key] ?? fallbackCatalog[key];
}

export function getMessage(locale: Locale, key: MessageKey): string {
  return resolveMessage(key, catalogs[locale], en);
}
