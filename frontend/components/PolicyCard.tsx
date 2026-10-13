'use client';
// F10: Policy Card. Shows the Policy Brain in plain language. All numbers/dates are formatted in code.
import { useTranslation } from 'react-i18next';
import Icon from './Icon';
import Link from 'next/link';
import AudioPlayer from './AudioPlayer';
import GlossaryText, { GlossaryProvider } from './GlossaryTip';
import LanguageSwitcher from './LanguageSwitcher';
import RedFlags from './RedFlags';
import { formatDate, formatInr } from '@/lib/format';
import type { Lang, PolicyBrain, Source } from '@/lib/types';

function SourceTag({ source }: { source: Source }) {
  const { t } = useTranslation();
  return (
    <span className="mt-1 block text-ink-muted">{t('common.source', { page: source.page, clause: source.clause })}</span>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-card bg-surface-sunken p-3">
      <dt className="text-ink-muted">{label}</dt>
      <dd className="mt-0.5 text-lg font-semibold">{value}</dd>
    </div>
  );
}

function ItemList({
  items,
  tone,
  empty,
}: {
  items: { text: string; source: Source }[];
  tone: 'ok' | 'no';
  empty: string;
}) {
  if (items.length === 0) return <p className="text-ink-muted">{empty}</p>;
  return (
    <ul className="space-y-3">
      {items.map((it, i) => (
        <li key={i} className="flex gap-3">
          <span
            aria-hidden="true"
            className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full font-bold ${
              tone === 'ok' ? 'bg-success-bg text-success-fg' : 'bg-danger-bg text-danger-fg'
            }`}
          >
            {tone === 'ok' ? '✓' : '✕'}
          </span>
          <span>
            <GlossaryText text={it.text} />
            <SourceTag source={it.source} />
          </span>
        </li>
      ))}
    </ul>
  );
}

export default function PolicyCard({ policy }: { policy: PolicyBrain }) {
  return (
    <GlossaryProvider>
      <PolicyCardBody policy={policy} />
    </GlossaryProvider>
  );
}

function PolicyCardBody({ policy }: { policy: PolicyBrain }) {
  const { t, i18n } = useTranslation();
  const lang = (['en', 'hi', 'mr'].includes(i18n.language) ? i18n.language : 'en') as Lang;
  const unknown = t('common.unknown');
  const speechText = [
    policy.plain_summary[lang],
    ...policy.red_flags.map((f) => `${f.title}. ${f.why_it_matters}`),
  ]
    .filter(Boolean)
    .join(' ');
  const wp = policy.waiting_periods;
  const cap = policy.room_rent_cap;

  const days = (n: number | null) => (n === null ? unknown : t('policy.days', { count: n }));
  const months = (n: number | null) => (n === null ? unknown : t('policy.months', { count: n }));
  const capText = !cap
    ? unknown
    : cap.unit === 'per_day'
      ? t('policy.capPerDay', { amount: formatInr(cap.value) })
      : t('policy.capPercent', { value: cap.value });

  return (
    <article className="space-y-4" aria-labelledby="policy-title">
      <header className="card">
        <p className="flex items-center gap-2 text-ink-muted">
          <Icon name="policy" className="h-5 w-5" />
          {policy.policy_type ? t(`policy.type.${policy.policy_type}`) : t('policy.title')}
        </p>
        <h1 id="policy-title" className="mt-1">
          {policy.insurer ?? unknown}
        </h1>
        <p className="mt-1 text-ink-soft">
          {t('policy.policyNo')}: {policy.policy_no ?? unknown}
        </p>
        {policy.holder_name && (
          <p className="text-ink-soft">
            {t('policy.holder')}: {policy.holder_name}
          </p>
        )}
      </header>

      <div className="card space-y-2">
        <p className="font-medium">{t('policy.readIn')}</p>
        <LanguageSwitcher className="w-full justify-between" />
        <p className="text-ink-muted">{t('policy.tapHint')}</p>
      </div>

      {policy.plain_summary[lang] && (
        <section className="card" aria-labelledby="sum-h">
          <h2 id="sum-h">{t('policy.summary')}</h2>
          <p className="mt-2" lang={lang}>
            <GlossaryText text={policy.plain_summary[lang]} />
          </p>
          <div className="mt-3">
            <AudioPlayer text={speechText} lang={lang} />
          </div>
        </section>
      )}

      <Link href={`/policy/ask?id=${encodeURIComponent(policy.policy_id)}`} className="btn-primary btn-lg w-full">
        {t('policy.askCta')}
      </Link>

      <RedFlags flags={policy.red_flags} />

      <section className="card" aria-labelledby="key-h">
        <h2 id="key-h">{t('policy.keyFacts')}</h2>
        <dl className="mt-3 grid grid-cols-2 gap-3">
          <Fact label={t('policy.sumInsured')} value={formatInr(policy.sum_insured)} />
          <Fact label={t('policy.premium')} value={formatInr(policy.premium)} />
          <Fact label={t('policy.startDate')} value={formatDate(policy.start_date)} />
          <Fact label={t('policy.endDate')} value={formatDate(policy.end_date)} />
          <Fact label={t('policy.renewalDate')} value={formatDate(policy.renewal_date)} />
        </dl>
      </section>

      <section className="card" aria-labelledby="cov-h">
        <h2 id="cov-h">{t('policy.covered')}</h2>
        <div className="mt-3">
          <ItemList items={policy.covered} tone="ok" empty={t('policy.noneListed')} />
        </div>
      </section>

      <section className="card" aria-labelledby="exc-h">
        <h2 id="exc-h">{t('policy.notCovered')}</h2>
        <div className="mt-3">
          <ItemList items={policy.exclusions} tone="no" empty={t('policy.noneListed')} />
        </div>
      </section>

      <section className="card" aria-labelledby="wait-h">
        <h2 id="wait-h">{t('policy.waiting')}</h2>
        <p className="mt-1 text-ink-muted">{t('policy.waitingHint')}</p>
        <dl className="mt-3 space-y-3">
          <Fact label={t('policy.waitInitial')} value={days(wp.initial_days)} />
          <Fact label={t('policy.waitPre')} value={months(wp.pre_existing_months)} />
          <Fact label={t('policy.waitSpecific')} value={months(wp.specific_diseases_months)} />
        </dl>
      </section>

      <section className="card" aria-labelledby="pay-h">
        <h2 id="pay-h">{t('policy.youPay')}</h2>
        <dl className="mt-3 space-y-3">
          <Fact
            label={t('policy.copay')}
            value={policy.copay_percent === null ? unknown : `${policy.copay_percent}%`}
          />
          <Fact label={t('policy.roomCap')} value={capText} />
        </dl>
        {policy.sub_limits.length > 0 && (
          <div className="mt-4">
            <h3>{t('policy.subLimits')}</h3>
            <ul className="mt-2 space-y-3">
              {policy.sub_limits.map((s, i) => (
                <li key={i}>
                  <span className="font-medium"><GlossaryText text={s.item} /></span>: {s.limit === null ? unknown : formatInr(s.limit)}
                  <SourceTag source={s.source} />
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
    </article>
  );
}
