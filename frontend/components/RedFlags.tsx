'use client';
// F11: Red Flags. Each flag = icon + title + plain explanation + source tag "page X, clause Y".
import { useTranslation } from 'react-i18next';
import GlossaryText from './GlossaryTip';
import Icon from './Icon';
import type { PolicyBrain } from '@/lib/types';

type Flag = PolicyBrain['red_flags'][number];

export default function RedFlags({ flags }: { flags: Flag[] }) {
  const { t } = useTranslation();
  return (
    <section className="card border-warning-line" aria-labelledby="rf-h">
      <h2 id="rf-h" className="flex items-center gap-2">
        <Icon name="flag" className="h-6 w-6 text-warning-solid" />
        {t('redFlags.title')}
      </h2>
      <p className="mt-1 text-ink-muted">{t('redFlags.hint')}</p>

      {flags.length === 0 ? (
        <p className="mt-3 chip-success">
          <span aria-hidden="true">✓</span> {t('redFlags.none')}
        </p>
      ) : (
        <ul className="mt-3 space-y-3">
          {flags.map((f, i) => (
            <li key={i} className="rounded-card border border-warning-line bg-warning-bg p-3 text-warning-fg">
              <p className="flex gap-2 font-semibold">
                <Icon name="flag" className="mt-0.5 h-5 w-5 shrink-0" />
                <span><GlossaryText text={f.title} /></span>
              </p>
              <p className="mt-2 pl-7">
                <span className="font-medium">{t('redFlags.why')}: </span>
                <GlossaryText text={f.why_it_matters} />
              </p>
              <p className="mt-2 pl-7 text-sm underline-offset-2">
                {t('common.source', { page: f.source.page, clause: f.source.clause })}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
