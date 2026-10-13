'use client';

import { useTranslation } from 'react-i18next';
import { LANGUAGES, isLang, setLanguage } from '@/lib/i18n';

/** Three large segmented buttons (EN / हिन्दी / मराठी). Choice is persisted by setLanguage(). */
export default function LanguageSwitcher({ className = '', compact = false }: { className?: string; compact?: boolean }) {
  const { t, i18n } = useTranslation();
  const current = isLang(i18n.language) ? i18n.language : 'en';

  return (
    <div role="group" aria-label={t('lang.choose')} className={`inline-flex rounded-card border border-surface-line bg-surface p-1 ${className}`}>
      {LANGUAGES.map((l) => {
        const active = l.code === current;
        return (
          <button
            key={l.code}
            type="button"
            lang={l.code}
            aria-pressed={active}
            aria-label={l.label}
            onClick={() => void setLanguage(l.code)}
            className={`min-h-touch min-w-touch rounded-[0.7rem] ${compact ? 'px-1' : 'px-3'} text-base font-semibold transition-colors ${
              active ? 'bg-brand-700 text-white' : 'text-ink-soft hover:bg-brand-50'
            }`}
          >
            {compact ? l.short : l.label}
          </button>
        );
      })}
    </div>
  );
}
