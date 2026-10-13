import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import en from '@/locales/en.json';
import hi from '@/locales/hi.json';
import mr from '@/locales/mr.json';

export const LANGUAGES = [
  { code: 'en', label: 'English', short: 'EN', locale: 'en-IN' },
  { code: 'hi', label: 'हिन्दी', short: 'हि', locale: 'hi-IN' },
  { code: 'mr', label: 'मराठी', short: 'मरा', locale: 'mr-IN' },
] as const;

export type LangCode = (typeof LANGUAGES)[number]['code'];
export const DEFAULT_LANG: LangCode = 'en';
export const LANG_STORAGE_KEY = 'bs_lang';

export function isLang(v: unknown): v is LangCode {
  return LANGUAGES.some((l) => l.code === v);
}

/** BCP-47 locale for speech and Intl (en-IN / hi-IN / mr-IN). */
export function localeOf(lang: string): string {
  return LANGUAGES.find((l) => l.code === lang)?.locale ?? 'en-IN';
}

export function readStoredLang(): LangCode | null {
  try {
    const v = window.localStorage.getItem(LANG_STORAGE_KEY);
    return isLang(v) ? v : null;
  } catch {
    return null; // storage can be blocked (private mode)
  }
}

export function detectBrowserLang(): LangCode {
  const nav = typeof navigator !== 'undefined' ? navigator.language?.toLowerCase() ?? '' : '';
  if (nav.startsWith('hi')) return 'hi';
  if (nav.startsWith('mr')) return 'mr';
  return DEFAULT_LANG;
}

// The server-rendered HTML (static export) is always English; the saved/detected
// language is applied after mount (see Providers) to avoid hydration mismatches.
if (!i18n.isInitialized) {
  i18n.use(initReactI18next).init({
    resources: {
      en: { translation: en },
      hi: { translation: hi },
      mr: { translation: mr },
    },
    lng: DEFAULT_LANG,
    fallbackLng: DEFAULT_LANG,
    supportedLngs: ['en', 'hi', 'mr'],
    interpolation: { escapeValue: false }, // React already escapes
    returnNull: false,
  });
}

/** Change language, persist the choice and keep <html lang> in sync. */
export async function setLanguage(lang: LangCode): Promise<void> {
  await i18n.changeLanguage(lang);
  if (typeof document !== 'undefined') document.documentElement.lang = lang;
  try {
    window.localStorage.setItem(LANG_STORAGE_KEY, lang);
  } catch {
    /* ignore: choice just won't persist */
  }
}

export default i18n;
