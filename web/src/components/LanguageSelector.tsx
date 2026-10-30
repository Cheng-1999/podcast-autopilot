import React from "react";
import { SUPPORTED_LOCALES, LOCALE_LABELS, isLocale, useLocale } from "../i18n";

export const LanguageSelector: React.FC = () => {
  const { locale, setLocale, t } = useLocale();

  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
      <label className="label-caps hide-on-mobile" htmlFor="language-select" style={{ color: "var(--text-muted)" }}>
        {t("language.selector.label")}
      </label>
      <select
        id="language-select"
        className="dense-select"
        aria-label={t("language.selector.label")}
        value={locale}
        onChange={(e) => {
          if (isLocale(e.target.value)) {
            setLocale(e.target.value);
          }
        }}
      >
        {SUPPORTED_LOCALES.map((code) => (
          <option key={code} value={code}>
            {LOCALE_LABELS[code]}
          </option>
        ))}
      </select>
    </div>
  );
};
