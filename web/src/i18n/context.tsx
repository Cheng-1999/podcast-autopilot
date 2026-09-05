import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { Locale } from "./types";
import { getMessage, type MessageKey } from "./messages";
import { interpolate } from "./format";
import { resolveInitialLocale, setStoredLocale } from "./storage";
import { applyDocumentLang } from "./dom";

interface LocaleContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: MessageKey, params?: Record<string, string | number>) => string;
}

const LocaleContext = createContext<LocaleContextValue | null>(null);

export const LocaleProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [locale, setLocaleState] = useState<Locale>(() => resolveInitialLocale());

  useEffect(() => {
    applyDocumentLang(locale);
    setStoredLocale(locale);
  }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
  }, []);

  const t = useCallback(
    (key: MessageKey, params?: Record<string, string | number>) => interpolate(getMessage(locale, key), params),
    [locale]
  );

  const value = useMemo<LocaleContextValue>(() => ({ locale, setLocale, t }), [locale, setLocale, t]);

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
};

export function useLocale(): LocaleContextValue {
  const ctx = useContext(LocaleContext);
  if (!ctx) {
    throw new Error("useLocale must be used within a LocaleProvider");
  }
  return ctx;
}
