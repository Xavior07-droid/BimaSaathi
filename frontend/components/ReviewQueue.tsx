'use client';
// F23: the review queue. Highest risk first. Each row opens the reasons drawer.
import { useTranslation } from 'react-i18next';
import { formatInr } from '@/lib/format';
import { actionKey, LEVEL_STYLE, riskLevel } from '@/lib/review';
import type { ReviewClaim } from '@/lib/types';

interface Props {
  claims: ReviewClaim[];
  onOpen: (claimId: string) => void;
}

export default function ReviewQueue({ claims, onOpen }: Props) {
  const { t } = useTranslation();
  return (
    <ul className="space-y-3" data-testid="review-queue">
      {claims.map((c) => {
        const level = riskLevel(c.risk_score);
        const s = LEVEL_STYLE[level];
        return (
          <li key={c.claim_id} className="card space-y-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="font-bold">{c.claim_id}</p>
                <p className="break-words text-ink-soft">{c.hospital}</p>
              </div>
              <span className={`${s.cls} font-semibold`}>
                <span aria-hidden="true">{s.icon}</span> {t(`review.level.${level}`)} · {c.risk_score}
              </span>
            </div>

            <dl className="grid grid-cols-2 gap-2">
              <div className="rounded-card bg-surface-sunken p-3">
                <dt className="text-ink-muted">{t('review.procedure')}</dt>
                <dd className="break-words font-semibold">{c.procedure}</dd>
              </div>
              <div className="rounded-card bg-surface-sunken p-3">
                <dt className="text-ink-muted">{t('review.amount')}</dt>
                <dd className="font-semibold">{formatInr(c.amount)}</dd>
              </div>
            </dl>

            <div className="flex flex-wrap items-center gap-2">
              <span className="chip-info">
                <span aria-hidden="true">👤</span> {t('review.human')}
              </span>
              <span className="chip-neutral">{t('review.flagCount', { count: c.flags.length })}</span>
              {c.action && (
                <span className="chip-success">
                  <span aria-hidden="true">✓</span> {t(`review.done.${actionKey(c.action)}`)}
                </span>
              )}
            </div>

            <button type="button" className="btn-secondary w-full" onClick={() => onOpen(c.claim_id)}>
              {t('review.seeReasons')}
              <span className="sr-only"> {c.claim_id}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
