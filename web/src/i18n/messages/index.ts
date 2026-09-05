import type { Locale } from "../types";
import en, { type MessageKey } from "./en";
import zhTW from "./zh-TW";
import zhCN from "./zh-CN";
import ja from "./ja";
import ko from "./ko";

export type { MessageKey };

// Every catalog other than the canonical `en` one is a Partial<MessageKey>:
// a key present in `en` but absent from a locale's catalog resolves to the
// English string via getMessage's fallback below.
const catalogs: Record<Locale, Partial<Record<MessageKey, string>>> = {
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
