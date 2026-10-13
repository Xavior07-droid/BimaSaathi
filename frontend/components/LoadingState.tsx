'use client';
// F25: one loading pattern for every screen. Spinner (default) or placeholder cards.
// A polite live region tells screen-reader users what is happening; motion respects reduced-motion.
import { useTranslation } from 'react-i18next';

interface Props {
  label?: string; // already translated; defaults to "Loading…"
  cards?: number; // show this many placeholder cards instead of a spinner
}

export default function LoadingState({ label, cards = 0 }: Props) {
  const { t } = useTranslation();
  const text = label ?? t('common.loading');
  if (cards > 0) {
    return (
      <div role="status" aria-live="polite" aria-busy="true">
        <span className="sr-only">{text}</span>
        <div className="space-y-4" aria-hidden="true">
          {Array.from({ length: cards }, (_, i) => (
            <div key={i} className="card h-32 bg-surface-sunken motion-safe:animate-pulse" />
          ))}
        </div>
      </div>
    );
  }
  return (
    <p role="status" aria-live="polite" className="flex items-center justify-center gap-3 py-8 text-ink-soft">
      <span aria-hidden="true" className="inline-block h-6 w-6 rounded-full border-2 border-current border-t-transparent motion-safe:animate-spin" />
      {text}
    </p>
  );
}
