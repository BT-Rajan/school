import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import ar from "./locales/ar";
import en from "./locales/en";

export type Locale = "en" | "ar";
const STORAGE_KEY = "sces.locale";

function storedLocale(): Locale | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "en" || value === "ar" ? value : null;
  } catch {
    return null;
  }
}

/** English is the default (D1). A choice made before sign-in is remembered on the device (FR-I3). */
export function initialLocale(): Locale {
  return storedLocale() ?? "en";
}

export function applyDocumentLocale(locale: Locale): void {
  document.documentElement.lang = locale;
  document.documentElement.dir = locale === "ar" ? "rtl" : "ltr";
}

export function setLocale(locale: Locale): void {
  // Changing language re-renders in place, so unsaved form input is kept.
  void i18n.changeLanguage(locale);
  applyDocumentLocale(locale);
  try {
    localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    // Storage can be unavailable in private windows; the choice still applies now.
  }
}

const locale = initialLocale();
void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, ar: { translation: ar } },
  lng: locale,
  fallbackLng: "en",
  interpolation: { escapeValue: false },
  returnNull: false,
});
applyDocumentLocale(locale);

export default i18n;
