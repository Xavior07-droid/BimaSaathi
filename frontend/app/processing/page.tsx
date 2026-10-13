'use client';
// Processing (F9): polls GET /api/policy/{id}/status and shows 4 progress stages,
// then opens the Policy Card. useSearchParams needs a Suspense boundary in a static export.
import { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useTranslation } from 'react-i18next';
import EmptyState from '@/components/EmptyState';
import { ApiError, errorMessageKey } from '@/lib/errors';
import { usePolicyStatus } from '@/lib/queries';
import type { IngestStage } from '@/lib/types';

const STAGES = ['uploading', 'reading', 'understanding', 'done'] as const;
const PERCENT: Record<IngestStage, number> = { uploading: 15, reading: 45, understanding: 75, done: 100, error: 0 };
const SLOW_AFTER_S = 45;

function Processing({ id }: { id: string }) {
  const { t } = useTranslation();
  const router = useRouter();
  const status = usePolicyStatus(id);
  const stage: IngestStage = status.data?.status ?? 'uploading';

  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const tick = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(tick);
  }, []);

  // Done: show the finished state for a moment, then open the card (replace: Back must not return here).
  useEffect(() => {
    if (stage !== 'done') return;
    const go = setTimeout(() => router.replace(`/policy?id=${encodeURIComponent(id)}`), 800);
    return () => clearTimeout(go);
  }, [stage, id, router]);

  // Failure = the backend reported an error, or polling itself kept failing.
  const failed = stage === 'error' || status.isError;
  if (failed) {
    const errKey = status.data?.error
      ? errorMessageKey(new ApiError(500, status.data.error))
      : errorMessageKey(status.error);
    return (
      <div className="space-y-4">
        <div role="alert" className="rounded-card border border-danger-line bg-danger-bg p-4 text-danger-fg">
          <p className="font-semibold">✕ {t('processing.errorTitle')}</p>
          <p className="mt-2">{t(errKey)}</p>
        </div>
        {status.isError && (
          <button type="button" onClick={() => void status.refetch()} className="btn-secondary w-full">
            {t('common.retry')}
          </button>
        )}
        <Link href="/" className="btn-primary w-full">
          {t('processing.again')}
        </Link>
      </div>
    );
  }

  const current = STAGES.indexOf(stage as (typeof STAGES)[number]);
  const pct = PERCENT[stage];

  return (
    <div className="space-y-5">
      <section>
        <h1>{t('processing.title')}</h1>
        <p className="mt-1 text-ink-soft">{t('processing.subtitle')}</p>
      </section>

      <div
        role="progressbar"
        aria-label={t('processing.progress')}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        className="h-4 w-full overflow-hidden rounded-pill bg-surface-sunken"
      >
        <div className="h-full rounded-pill bg-brand-600 transition-all duration-700" style={{ width: `${pct}%` }} />
      </div>

      <ol className="card space-y-4" aria-live="polite">
        {STAGES.map((s, i) => {
          const state = i < current || stage === 'done' ? 'done' : i === current ? 'active' : 'todo';
          return (
            <li key={s} className="flex items-center gap-3" aria-current={state === 'active' ? 'step' : undefined}>
              <span
                aria-hidden="true"
                className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full font-bold ${
                  state === 'done'
                    ? 'bg-success-bg text-success-fg'
                    : state === 'active'
                      ? 'bg-brand-100 text-brand-800'
                      : 'bg-surface-sunken text-ink-muted'
                }`}
              >
                {state === 'done' ? (
                  '✓'
                ) : state === 'active' ? (
                  <span className="inline-block h-5 w-5 rounded-full border-2 border-current border-t-transparent motion-safe:animate-spin" />
                ) : (
                  i + 1
                )}
              </span>
              <span className={state === 'todo' ? 'text-ink-muted' : state === 'active' ? 'font-semibold' : ''}>
                {t(`processing.stages.${s}`)}
              </span>
            </li>
          );
        })}
      </ol>

      <p className="text-center text-ink-muted">
        {stage === 'done' ? t('processing.opening') : t('processing.elapsed', { seconds: elapsed })}
      </p>

      {elapsed >= SLOW_AFTER_S && stage !== 'done' && (
        <p role="status" className="rounded-card border border-warning-line bg-warning-bg p-3 text-warning-fg">
          {t('processing.slow')}
        </p>
      )}
    </div>
  );
}

function ProcessingRoute() {
  const { t } = useTranslation();
  const id = useSearchParams().get('id');
  if (!id) {
    return (
      <EmptyState
        title={t('processing.noIdTitle')}
        body={t('processing.noIdBody')}
        action={{ label: t('processing.goHome'), href: '/' }}
      />
    );
  }
  return <Processing id={id} />;
}

export default function ProcessingPage() {
  return (
    <Suspense fallback={null}>
      <ProcessingRoute />
    </Suspense>
  );
}
