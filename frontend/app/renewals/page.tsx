'use client';
// F22: Renewals. Policy list with status chips, edit date, test reminder, add to calendar,
// and the notification permission card (FCM token + service worker, see lib/push.ts).
import { useState } from 'react';
import Link from 'next/link';
import { useTranslation } from 'react-i18next';
import EmptyState from '@/components/EmptyState';
import ErrorState from '@/components/ErrorState';
import LoadingState from '@/components/LoadingState';
import PushCard from '@/components/PushCard';
import { errorMessageKey } from '@/lib/errors';
import { formatDate, formatInr } from '@/lib/format';
import { buildIcs, downloadIcs } from '@/lib/ics';
import type { PushState } from '@/lib/push';
import { useReminders, useTestReminder, useUpdateReminder } from '@/lib/queries';
import { daysUntil, isRealIsoDate, nextReminder, renewalStatus } from '@/lib/renewal';
import type { Reminder } from '@/lib/types';

const CHIP: Record<ReturnType<typeof renewalStatus>, { cls: string; icon: string; key: string }> = {
  upcoming: { cls: 'chip-info', icon: '●', key: 'renewals.status.upcoming' },
  due_soon: { cls: 'chip-warning', icon: '!', key: 'renewals.status.dueSoon' },
  expired: { cls: 'chip-danger', icon: '✕', key: 'renewals.status.expired' },
  no_date: { cls: 'chip-neutral', icon: '?', key: 'renewals.status.noDate' },
};

function ReminderCard({ r, pushState }: { r: Reminder; pushState: PushState }) {
  const { t } = useTranslation();
  const update = useUpdateReminder();
  const test = useTestReminder();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(r.renewal_date ?? '');
  const [errKey, setErrKey] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  // Days left and status are worked out here from the date, so they update the moment the date is edited.
  const days = daysUntil(r.renewal_date);
  const status = renewalStatus(days);
  const chip = CHIP[status];
  const next = nextReminder(r.renewal_date, r.sent_flags);
  const canTest = pushState === 'on';

  const save = () => {
    if (!draft || !isRealIsoDate(draft) || draft < '2000-01-01' || draft > '2100-12-31') {
      setErrKey('renewals.errDate');
      return;
    }
    setErrKey(null);
    update.mutate(
      { id: r.policy_id, date: draft },
      {
        onSuccess: () => {
          setEditing(false);
          setSaved(true);
        },
      },
    );
  };

  const addToCalendar = () => {
    if (!r.renewal_date) return;
    downloadIcs(
      `renewal-${r.renewal_date}.ics`,
      buildIcs({
        policyId: r.policy_id,
        policyName: r.policy_name,
        renewalDate: r.renewal_date,
        premium: r.premium,
        title: t('renewals.calTitle'),
        note: t('renewals.calNote'),
      }),
    );
  };

  return (
    <li className="card space-y-3" data-testid="renewal-card">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h2 className="min-w-0 break-words text-lg">{r.policy_name}</h2>
        <span className={`${chip.cls} font-semibold`}>
          <span aria-hidden="true">{chip.icon}</span> {t(chip.key)}
        </span>
      </div>

      <dl className="grid grid-cols-2 gap-2">
        <div className="rounded-card bg-surface-sunken p-3">
          <dt className="text-ink-muted">{t('policy.renewalDate')}</dt>
          <dd className="font-semibold">{formatDate(r.renewal_date)}</dd>
        </div>
        <div className="rounded-card bg-surface-sunken p-3">
          <dt className="text-ink-muted">{t('policy.premium')}</dt>
          <dd className="font-semibold">{formatInr(r.premium)}</dd>
        </div>
      </dl>

      {days !== null && (
        <p className="font-semibold" data-testid="days-left">
          {days < 0
            ? t('renewals.daysAgo', { count: Math.abs(days) })
            : days === 0
              ? t('renewals.today')
              : t('renewals.daysLeft', { count: days })}
        </p>
      )}

      {status !== 'expired' && status !== 'no_date' && (
        <p className="text-ink-soft">
          {next ? t('renewals.nextReminder', { date: formatDate(next.date), days: next.daysBefore }) : t('renewals.noMoreReminders')}
        </p>
      )}
      {r.sent_flags.length > 0 && (
        <p className="text-ink-muted">{t('renewals.sent', { list: [...r.sent_flags].sort((a, b) => b - a).join(', ') })}</p>
      )}

      {editing ? (
        <div className="space-y-2 rounded-card border border-surface-line p-3">
          <label htmlFor={`date-${r.policy_id}`} className="block text-lg font-semibold">
            {t('renewals.newDate')}
          </label>
          <input
            id={`date-${r.policy_id}`}
            type="date"
            className="input"
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              setErrKey(null);
            }}
            aria-invalid={!!errKey}
            aria-describedby={errKey ? `date-err-${r.policy_id}` : undefined}
          />
          {errKey && (
            <p id={`date-err-${r.policy_id}`} role="alert" className="flex gap-1 text-danger-fg">
              <span aria-hidden="true">⚠</span> {t(errKey)}
            </p>
          )}
          {update.isError && (
            <p role="alert" className="flex gap-1 text-danger-fg">
              <span aria-hidden="true">✕</span> {t(errorMessageKey(update.error))}
            </p>
          )}
          <div className="grid grid-cols-2 gap-2">
            <button type="button" className="btn-primary" onClick={save} disabled={update.isPending}>
              {update.isPending ? t('renewals.saving') : t('common.save')}
            </button>
            <button
              type="button"
              className="btn-secondary"
              disabled={update.isPending}
              onClick={() => {
                setEditing(false);
                setErrKey(null);
                setDraft(r.renewal_date ?? '');
                update.reset();
              }}
            >
              {t('common.cancel')}
            </button>
          </div>
        </div>
      ) : (
        <div className="grid gap-2">
          <button
            type="button"
            className="btn-secondary w-full"
            onClick={() => {
              setDraft(r.renewal_date ?? '');
              setSaved(false);
              setEditing(true);
            }}
          >
            {t('renewals.change')}
          </button>
          <button type="button" className="btn-secondary w-full" onClick={addToCalendar} disabled={!r.renewal_date}>
            {t('renewals.addCal')}
          </button>
          <button
            type="button"
            className="btn-secondary w-full"
            onClick={() => test.mutate(r.policy_id)}
            disabled={!canTest || test.isPending}
          >
            {test.isPending ? t('renewals.testing') : t('renewals.test')}
          </button>
          {!canTest && <p className="text-ink-muted">{t('renewals.testNeedPush')}</p>}
          {(status === 'due_soon' || status === 'expired') && (
            <Link href="/compare" className="btn-ghost w-full">
              {t('renewals.compareCta')}
            </Link>
          )}
        </div>
      )}

      {saved && !editing && (
        <p role="status" className="chip-success">
          <span aria-hidden="true">✓</span> {t('renewals.saved')}
        </p>
      )}
      {test.isSuccess && (
        <p role="status" className={test.data.sent ? 'chip-success' : 'chip-warning'}>
          <span aria-hidden="true">{test.data.sent ? '✓' : '!'}</span> {t(test.data.sent ? 'renewals.testSent' : 'renewals.testNotSent')}
        </p>
      )}
      {test.isError && (
        <p role="alert" className="flex gap-1 text-danger-fg">
          <span aria-hidden="true">✕</span> {t(errorMessageKey(test.error))}
        </p>
      )}
    </li>
  );
}

export default function RenewalsPage() {
  const { t } = useTranslation();
  const reminders = useReminders();
  const [pushState, setPushState] = useState<PushState>('checking');

  return (
    <div className="space-y-5">
      <header>
        <h1>{t('renewals.title')}</h1>
        <p className="mt-1 text-ink-soft">{t('renewals.subtitle')}</p>
      </header>

      <PushCard onStateChange={setPushState} />

      {reminders.isLoading && <LoadingState cards={2} />}

      {reminders.isError && <ErrorState error={reminders.error} onRetry={() => void reminders.refetch()} retrying={reminders.isRefetching} />}

      {reminders.data && reminders.data.length === 0 && (
        <EmptyState
          icon="bell"
          title={t('renewals.emptyTitle')}
          body={t('renewals.emptyBody')}
          action={{ label: t('processing.goHome'), href: '/' }}
        />
      )}

      {reminders.data && reminders.data.length > 0 && (
        <ul className="space-y-4">
          {reminders.data.map((r) => (
            <ReminderCard key={r.policy_id} r={r} pushState={pushState} />
          ))}
        </ul>
      )}
    </div>
  );
}
