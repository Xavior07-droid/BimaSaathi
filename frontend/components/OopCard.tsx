'use client';
// F21: out-of-pocket card for one policy. Every number comes from the backend calculator (code),
// the card only formats them. Best fit = badge with icon + text (not colour alone).
import { useTranslation } from 'react-i18next';
import { formatInr } from '@/lib/format';
import type { CompareOutcome } from '@/lib/types';

interface Props {
  outcome: CompareOutcome;
  insurer: string | null;
  bill: number;
  isBest: boolean;
}

export default function OopCard({ outcome, insurer, bill, isBest }: Props) {
  const { t } = useTranslation();
  const oop = outcome.out_of_pocket;
  const policyPays = Math.max(0, bill - oop);
  const pct = bill > 0 ? Math.min(100, Math.round((oop / bill) * 100)) : 0;
  const name = insurer ?? t('common.unknown');

  return (
    <li className={`card space-y-3 ${isBest ? 'border-2 border-success-solid' : ''}`} data-testid="oop-card">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="min-w-0 break-words">{name}</h3>
        {isBest && (
          <span className="chip-success font-semibold">
            <span aria-hidden="true">★</span> {t('compare.bestFit')}
          </span>
        )}
      </div>

      <div>
        <p className="text-ink-soft">{t('compare.youPay')}</p>
        <p className="text-3xl font-bold" data-testid="oop-amount">
          {formatInr(oop)}
        </p>
        <p className="text-ink-muted">{t('compare.ofBill', { pct })}</p>
      </div>

      <dl className="space-y-2">
        <div className="flex justify-between gap-3 rounded-card bg-surface-sunken p-3">
          <dt className="text-ink-soft">{t('compare.policyPays')}</dt>
          <dd className="font-semibold">{formatInr(policyPays)}</dd>
        </div>
        <div className="flex justify-between gap-3 rounded-card bg-surface-sunken p-3">
          <dt className="text-ink-soft">{t('compare.includesCopay')}</dt>
          <dd className="font-semibold">{formatInr(outcome.copay_amount)}</dd>
        </div>
      </dl>

      {outcome.how_calculated.length > 0 && (
        <details>
          <summary className="min-h-touch cursor-pointer py-2 font-semibold text-brand-800">{t('compare.howTitle')}</summary>
          <ol className="mt-1 list-decimal space-y-1 pl-6 text-ink-soft">
            {outcome.how_calculated.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ol>
        </details>
      )}
    </li>
  );
}
