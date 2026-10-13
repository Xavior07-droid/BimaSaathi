'use client';
// F12: tap-to-explain jargon. <GlossaryProvider> holds one shared bottom sheet;
// <GlossaryText> underlines known terms inside any text and opens the sheet on tap.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { splitByGlossary, type GlossaryEntry } from '@/lib/glossary';
import type { Lang } from '@/lib/types';

interface Ctx {
  open: (entry: GlossaryEntry) => void;
}
const GlossaryCtx = createContext<Ctx | null>(null);

function useLang(): Lang {
  const { i18n } = useTranslation();
  return (['en', 'hi', 'mr'].includes(i18n.language) ? i18n.language : 'en') as Lang;
}

export function GlossaryProvider({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation();
  const lang = useLang();
  const [entry, setEntry] = useState<GlossaryEntry | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const opener = useRef<HTMLElement | null>(null);

  const open = useCallback((e: GlossaryEntry) => {
    opener.current = document.activeElement as HTMLElement | null;
    setEntry(e);
  }, []);
  const close = useCallback(() => {
    setEntry(null);
    opener.current?.focus(); // give focus back to the word that was tapped
  }, []);

  useEffect(() => {
    if (!entry) return;
    closeRef.current?.focus();
    const onKey = (ev: KeyboardEvent) => ev.key === 'Escape' && close();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [entry, close]);

  const value = useMemo(() => ({ open }), [open]);

  return (
    <GlossaryCtx.Provider value={value}>
      {children}
      {entry && (
        <>
          <div className="fixed inset-0 z-40 bg-ink/30" onClick={close} aria-hidden="true" />
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="gl-term"
            className="fixed inset-x-0 bottom-0 z-50 mx-auto w-full max-w-app rounded-t-card bg-surface p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] shadow-sheet"
          >
            <h2 id="gl-term" lang={lang}>
              {entry.term[lang]}
            </h2>
            <p className="mt-2 text-lg" lang={lang}>
              {entry.meaning[lang]}
            </p>
            <button ref={closeRef} type="button" className="btn-primary mt-4 w-full" onClick={close}>
              {t('common.close')}
            </button>
          </div>
        </>
      )}
    </GlossaryCtx.Provider>
  );
}

/** Renders text with known insurance terms underlined and tappable. Plain text if no provider. */
export default function GlossaryText({ text }: { text: string }) {
  const lang = useLang();
  const ctx = useContext(GlossaryCtx);
  const pieces = useMemo(() => (ctx ? splitByGlossary(text, lang) : [text]), [text, lang, ctx]);
  return (
    <>
      {pieces.map((p, i) =>
        typeof p === 'string' ? (
          <span key={i}>{p}</span>
        ) : (
          <button
            key={i}
            type="button"
            onClick={() => ctx!.open(p.entry)}
            className="inline cursor-help rounded-sm font-medium text-brand-800 underline decoration-dotted decoration-2 underline-offset-4"
          >
            {p.text}
          </button>
        ),
      )}
    </>
  );
}
