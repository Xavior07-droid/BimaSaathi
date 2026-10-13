'use client';
// F20: side-by-side policy table. Wide on purpose: it scrolls sideways inside its own box
// (the page itself never scrolls sideways) and the row labels stay pinned on the left.
// All values are formatted in code from the backend's normalised rows.
import { useTranslation } from 'react-i18next';
import { formatInr } from '@/lib/format';
import type { CompareRow } from '@/lib/types';

type TFn = (key: string, opts?: Record<string, unknown>) => string;

const periodDays = (t: TFn, n: number | null) => (n === null ? null : t('policy.days', { count: n }));
const periodMonths = (t: TFn, n: number | null) => (n === null ? null : t('policy.months', { count: n }));

function roomCap(t: TFn, c: CompareRow['room_rent_cap']): string | null {
  if (!c) return null;
  return c.unit === 'per_day'
    ? t('policy.capPerDay', { amount: formatInr(c.value) })
    : t('policy.capPercent', { value: c.value });
}

interface Line {
  key: string;
  label: string;
  cell: (r: CompareRow) => string | string[] | null;
}

export default function CompareTable({ rows }: { rows: CompareRow[] }) {
  const { t } = useTranslation();
  const tt = t as unknown as TFn;
  const lines: Line[] = [
    { key: 'premium', label: t('policy.premium'), cell: (r) => (r.premium === null ? null : formatInr(r.premium)) },
    { key: 'sum', label: t('policy.sumInsured'), cell: (r) => (r.sum_insured === null ? null : formatInr(r.sum_insured)) },
    { key: 'w1', label: t('policy.waitInitial'), cell: (r) => periodDays(tt, r.waiting_periods.initial_days) },
    { key: 'w2', label: t('policy.waitPre'), cell: (r) => periodMonths(tt, r.waiting_periods.pre_existing_months) },
    { key: 'w3', label: t('policy.waitSpecific'), cell: (r) => periodMonths(tt, r.waiting_periods.specific_diseases_months) },
    { key: 'copay', label: t('policy.copay'), cell: (r) => (r.copay_percent === null ? null : `${r.copay_percent}%`) },
    { key: 'room', label: t('policy.roomCap'), cell: (r) => roomCap(tt, r.room_rent_cap) },
    { key: 'excl', label: t('compare.exclusions'), cell: (r) => (r.key_exclusions.length ? r.key_exclusions : [t('compare.noExclusions')]) },
  ];

  return (
    <div>
      <p className="mb-2 text-ink-muted" aria-hidden="true">
        ⇆ {t('compare.swipe')}
      </p>
      {/* tabIndex + role=region: keyboard users can scroll the table with the arrow keys */}
      <div
        role="region"
        aria-label={t('compare.tableTitle')}
        tabIndex={0}
        className="overflow-x-auto rounded-card border border-surface-line bg-surface"
        data-testid="compare-scroll"
      >
        <table className="w-full min-w-max border-collapse text-left">
          <caption className="sr-only">{t('compare.tableTitle')}</caption>
          <thead>
            <tr className="bg-surface-sunken">
              <th scope="col" className="sticky left-0 z-10 w-32 min-w-[8rem] bg-surface-sunken p-3 font-semibold text-ink-muted">
                <span className="sr-only">{t('compare.feature')}</span>
              </th>
              {rows.map((r, i) => (
                <th key={r.policy_id} scope="col" className="min-w-[10rem] max-w-[14rem] p-3 align-bottom">
                  <span className="block font-normal text-ink-muted">{t('compare.policyN', { n: i + 1 })}</span>
                  <span className="block text-lg font-bold">{r.insurer ?? t('common.unknown')}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => (
              <tr key={l.key} className="border-t border-surface-line align-top">
                <th scope="row" className="sticky left-0 z-10 w-32 min-w-[8rem] bg-surface p-3 font-semibold text-ink-soft">
                  {l.label}
                </th>
                {rows.map((r) => {
                  const v = l.cell(r);
                  return (
                    <td key={r.policy_id} className="min-w-[10rem] max-w-[14rem] p-3">
                      {v === null ? (
                        <span className="text-ink-muted">{t('compare.notMentioned')}</span>
                      ) : Array.isArray(v) ? (
                        <ul className="list-disc space-y-1 pl-5">
                          {v.map((x, i) => (
                            <li key={i}>{x}</li>
                          ))}
                        </ul>
                      ) : (
                        <span className="font-semibold">{v}</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
