'use client';
// F23: Review dashboard (insurer view, demo). Claims ranked by a rule-based risk score for HUMAN review.
// Never auto-rejects and never labels a person. Always shows the "Synthetic data" banner.
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import EmptyState from '@/components/EmptyState';
import ErrorState from '@/components/ErrorState';
import LoadingState from '@/components/LoadingState';
import ReviewDrawer from '@/components/ReviewDrawer';
import ReviewQueue from '@/components/ReviewQueue';
import { useReviewClaims } from '@/lib/queries';
import { riskLevel } from '@/lib/review';

type Filter = 'all' | 'open' | 'done';
const FILTERS: Filter[] = ['all', 'open', 'done'];

export default function ReviewPage() {
  const { t } = useTranslation();
  const q = useReviewClaims();
  const [filter, setFilter] = useState<Filter>('all');
  const [openId, setOpenId] = useState<string | null>(null);

  const all = q.data ? [...q.data.claims].sort((a, b) => b.risk_score - a.risk_score) : [];
  const done = all.filter((c) => c.action !== null).length;
  const shown = all.filter((c) => (filter === 'all' ? true : filter === 'open' ? c.action === null : c.action !== null));
  const high = all.filter((c) => riskLevel(c.risk_score) === 'high').length;
  const selected = all.find((c) => c.claim_id === openId) ?? null;

  return (
    <div className="space-y-5">
      {/* Always visible, whatever the API says: this screen only ever shows made-up claims. */}
      <p role="note" className="flex gap-2 rounded-card border-2 border-warning-solid bg-warning-bg p-3 font-semibold text-warning-fg">
        <span aria-hidden="true">⚠</span>
        <span>{t('review.synthetic')}</span>
      </p>

      <header>
        <h1>{t('review.title')}</h1>
        <p className="mt-1 text-ink-soft">{t('review.subtitle')}</p>
        <p className="mt-2 flex flex-wrap gap-2">
          <span className="chip-info font-semibold">
            <span aria-hidden="true">👤</span> {t('review.human')}
          </span>
        </p>
      </header>

      {q.isLoading && <LoadingState cards={3} />}

      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} retrying={q.isRefetching} />}

      {q.data && all.length === 0 && (
        <EmptyState icon="policy" title={t('review.emptyTitle')} body={t('review.emptyBody')} />
      )}

      {q.data && all.length > 0 && (
        <>
          <section className="card space-y-1" aria-label={t('review.summaryLabel')}>
            <p className="font-semibold">{t('review.summary', { count: all.length, high })}</p>
            <p className="text-ink-soft">{t('review.reviewedCount', { done, total: all.length })}</p>
          </section>

          <div role="group" aria-label={t('review.filterLabel')} className="grid grid-cols-3 gap-2">
            {FILTERS.map((f) => (
              <button
                key={f}
                type="button"
                aria-pressed={filter === f}
                className={filter === f ? 'btn-primary' : 'btn-secondary'}
                onClick={() => setFilter(f)}
              >
                {t(`review.filter.${f}`)}
              </button>
            ))}
          </div>

          {shown.length === 0 ? (
            <p className="rounded-card border border-surface-line p-4 text-center text-ink-soft">{t('review.filterEmpty')}</p>
          ) : (
            <ReviewQueue claims={shown} onOpen={setOpenId} />
          )}
        </>
      )}

      <ReviewDrawer claim={selected} onClose={() => setOpenId(null)} />
    </div>
  );
}
