import { describe, it, expect } from "vitest";
import { interpolate } from "../src/i18n/format";
import { applyDocumentLang } from "../src/i18n/dom";
import { getMessage, resolveMessage } from "../src/i18n/messages";
import { isLocale, SUPPORTED_LOCALES } from "../src/i18n/types";
import {
  LOCALE_STORAGE_KEY,
  getStoredLocale,
  setStoredLocale,
  matchBrowserLocale,
  resolveInitialLocale,
} from "../src/i18n/storage";

function fakeStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (key: string) => (data.has(key) ? data.get(key)! : null),
    setItem: (key: string, value: string) => {
      data.set(key, value);
    },
  };
}

describe("isLocale", () => {
  it("accepts every supported locale", () => {
    for (const locale of SUPPORTED_LOCALES) {
      expect(isLocale(locale)).toBe(true);
    }
  });

  it("rejects unsupported or non-string values", () => {
    expect(isLocale("fr")).toBe(false);
    expect(isLocale(null)).toBe(false);
    expect(isLocale(undefined)).toBe(false);
    expect(isLocale(42)).toBe(false);
  });
});

describe("interpolate", () => {
  it("substitutes a placeholder with the given param", () => {
    expect(interpolate("Welcome back, {{name}}", { name: "Ada" })).toBe("Welcome back, Ada");
  });

  it("substitutes multiple distinct placeholders", () => {
    expect(interpolate("{{a}} and {{b}}", { a: "x", b: "y" })).toBe("x and y");
  });

  it("leaves a placeholder untouched when its param is missing", () => {
    expect(interpolate("Hi {{name}}", {})).toBe("Hi {{name}}");
  });

  it("returns the template unchanged when no params are given", () => {
    expect(interpolate("Hi {{name}}")).toBe("Hi {{name}}");
  });

  it("stringifies numeric params", () => {
    expect(interpolate("{{count}} items", { count: 3 })).toBe("3 items");
  });
});

describe("resolveMessage (fallback contract)", () => {
  const fallback = { a: "A", b: "B" };
  const partial: Partial<Record<"a" | "b", string>> = { a: "translated-a" };

  it("uses the locale catalog's own value when present", () => {
    expect(resolveMessage("a", partial, fallback)).toBe("translated-a");
  });

  it("falls back to the canonical catalog when the key is missing", () => {
    expect(resolveMessage("b", partial, fallback)).toBe("B");
  });
});

describe("getMessage", () => {
  it("returns a real translation for every supported locale", () => {
    for (const locale of SUPPORTED_LOCALES) {
      expect(getMessage(locale, "language.selector.label")).toBeTruthy();
    }
  });

  it("interpolation-ready keys still contain their placeholder", () => {
    expect(getMessage("en", "greeting.welcome")).toContain("{{name}}");
  });

  it("resolves representative dashboard copy in every locale", () => {
    const keys = ["episodes.heading", "new.heading", "detail.review", "clips.heading", "deliverables.heading", "controls.run", "transcript.search"] as const;
    for (const locale of SUPPORTED_LOCALES) {
      for (const key of keys) expect(getMessage(locale, key)).not.toBe(key);
    }
  });
});

describe("locale persistence", () => {
  it("returns null when nothing is stored", () => {
    expect(getStoredLocale(fakeStorage())).toBeNull();
  });

  it("returns null when the stored value is not a supported locale", () => {
    expect(getStoredLocale(fakeStorage({ [LOCALE_STORAGE_KEY]: "fr" }))).toBeNull();
  });

  it("returns the stored locale when it is valid", () => {
    expect(getStoredLocale(fakeStorage({ [LOCALE_STORAGE_KEY]: "ja" }))).toBe("ja");
  });

  it("round-trips a value written by setStoredLocale", () => {
    const storage = fakeStorage();
    setStoredLocale("ko", storage);
    expect(getStoredLocale(storage)).toBe("ko");
  });

  it("does not throw when the underlying storage throws", () => {
    const throwingStorage = {
      getItem: () => {
        throw new Error("blocked");
      },
    };
    expect(() => getStoredLocale(throwingStorage)).not.toThrow();
    expect(getStoredLocale(throwingStorage)).toBeNull();
  });
});

describe("matchBrowserLocale", () => {
  it("matches an exact supported tag", () => {
    expect(matchBrowserLocale(["zh-TW"])).toBe("zh-TW");
  });

  it("matches a region-qualified tag to its primary subtag", () => {
    expect(matchBrowserLocale(["en-US"])).toBe("en");
    expect(matchBrowserLocale(["ja-JP"])).toBe("ja");
    expect(matchBrowserLocale(["ko-KR"])).toBe("ko");
  });

  it("maps mainland/Singapore Chinese regions to zh-CN", () => {
    expect(matchBrowserLocale(["zh-CN"])).toBe("zh-CN");
    expect(matchBrowserLocale(["zh-SG"])).toBe("zh-CN");
    expect(matchBrowserLocale(["zh-Hans-CN"])).toBe("zh-CN");
  });

  it("maps other Chinese regions and a bare zh tag to zh-TW", () => {
    expect(matchBrowserLocale(["zh-HK"])).toBe("zh-TW");
    expect(matchBrowserLocale(["zh-MO"])).toBe("zh-TW");
    expect(matchBrowserLocale(["zh"])).toBe("zh-TW");
  });

  it("returns the first match across an ordered language list", () => {
    expect(matchBrowserLocale(["fr-FR", "ja-JP", "en-US"])).toBe("ja");
  });

  it("returns null when nothing matches", () => {
    expect(matchBrowserLocale(["fr-FR", "de-DE"])).toBeNull();
  });
});

describe("resolveInitialLocale", () => {
  it("prefers a stored valid locale over the browser language", () => {
    const locale = resolveInitialLocale({
      storage: fakeStorage({ [LOCALE_STORAGE_KEY]: "ko" }),
      languages: ["en-US"],
    });
    expect(locale).toBe("ko");
  });

  it("falls back to browser language matching when nothing is stored", () => {
    const locale = resolveInitialLocale({
      storage: fakeStorage(),
      languages: ["ja-JP"],
    });
    expect(locale).toBe("ja");
  });

  it("falls back to zh-TW when neither storage nor browser language matches", () => {
    const locale = resolveInitialLocale({
      storage: fakeStorage(),
      languages: ["fr-FR"],
    });
    expect(locale).toBe("zh-TW");
  });
});

describe("applyDocumentLang", () => {
  it("sets documentElement.lang to the given locale", () => {
    const doc = { documentElement: { lang: "" } };
    applyDocumentLang("ja", doc);
    expect(doc.documentElement.lang).toBe("ja");
  });

  it("overwrites a previously set lang value", () => {
    const doc = { documentElement: { lang: "en" } };
    applyDocumentLang("zh-CN", doc);
    expect(doc.documentElement.lang).toBe("zh-CN");
  });
});
