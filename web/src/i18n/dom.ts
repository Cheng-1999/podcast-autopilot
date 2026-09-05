import type { Locale } from "./types";

interface LangTarget {
  documentElement: { lang: string };
}

export function applyDocumentLang(locale: Locale, doc: LangTarget = document): void {
  doc.documentElement.lang = locale;
}
