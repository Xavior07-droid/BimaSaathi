'use client';
// F23: bottom-sheet drawer with the reasons for a claim and the three human actions.
// Built on the native <dialog>: focus is trapped, Esc closes it and the page behind is inert.
import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { errorMessageKey } from '@/lib/errors';
import { formatInr } from '@/lib/format';
import { useReviewAction } from '@/lib/queries';
import { ACTIONS, actionKey, LEVEL_STYLE, riskLevel } from '@/lib/review';
import type { ReviewClaim } from '@/lib/types';

interface Props {
  claim: ReviewClaim | null;
  onClose: () => void;
}

export default function ReviewDrawer({ claim, onClose }: Props) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDialogElement>(null);
  const act = useReviewAction();
  const open = claim !== null;

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
    document.body.style.overflow = open ? 'hidden' : '';
    return () => {
      document.body.style.overflow = '';
    };
  }, [open]);

  useEffect(() => {
    act.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [claim?.claim_id]);

  const level = claim ? riskLevel(claim.risk_score) : 'low';
  const s = LEVEL_STYLE[level];

  return (
    <dialog
      ref={ref}
      aria-labelledby="drawer-h"
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) ref.current?.close(); // tap on the dimmed area
      }}
      className="fixed inset-x-0 bottom-0 top-auto m-0 max-h-[88vh] w-full max-w-none overflow-y-auto rounded-t-2xl border-0 bg-surface p-0 text-ink shadow-card backdrop:bg-black/50"
    >
      {claim && (
        <div className="space-y-4 p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h2 id="drawer-h" className="break-words">
                {claim.claim_id}
              </h2>
              <p className="text-ink-soft">
                {claim.hospital} · {claim.procedure} · {formatInr(claim.amount)}
              </p>
            </div>
            <button type="button" className="btn-ghost shrink-0" onClick={() => ref.current?.close()}>
              {t('review.close')}
            </button>
          </div>

          <p className="flex flex-wrap gap-2">
            <span className={`${s.cls} font-semibold`}>
              <span aria-hidden="true">{s.icon}</span> {t(`review.level.${level}`)} · {t('review.score', { score: claim.risk_score })}
            </span>
            <span className="chip-info">
              <span aria-hidden="true">👤</span> {t('review.human')}
            </span>
          </p>
          <p className="rounded-card border border-info-line bg-info-bg p-3 text-info-fg">{t('review.humanNote')}</p>

          <section aria-labelledby="why-h" className="space-y-2">
            <h3 id="why-h">{t('review.reasonsTitle')}</h3>
            {claim.flags.length === 0 ? (
              <p className="text-ink-soft">{t('review.noFlags')}</p>
            ) : (
              <ul className="space-y-2">
                {claim.flags.map((f, i) => {
                  const fs = LEVEL_STYLE[f.severity];
                  return (
                    <li key={`${f.rule}-${i}`} className="rounded-card border border-surface-line p-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="font-semibold">
                          {f.rule}: {t(`review.rules.${f.rule}`)}
                        </p>
                        <span className={fs.cls}>
                          <span aria-hidden="true">{fs.icon}</span> {t(`review.level.${f.severity}`)}
                        </span>
                      </div>
                      <p className="mt-1 text-ink-soft">{f.reason}</p>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <section aria-labelledby="act-h" className="space-y-2">
            <h3 id="act-h">{t('review.actionsTitle')}</h3>
            {claim.action && (
              <p role="status" className="chip-success">
                <span aria-hidden="true">✓</span> {t(`review.done.${actionKey(claim.action)}`)}
              </p>
            )}
            <div className="grid gap-2">
              {ACTIONS.map((a) => (
                <button
                  key={a.value}
                  type="button"
                  className={claim.action === a.value ? 'btn-primary w-full' : 'btn-secondary w-full'}
                  aria-pressed={claim.action === a.value}
                  disabled={act.isPending}
                  onClick={() => act.mutate({ id: claim.claim_id, action: a.value })}
                >
                  {act.isPending && act.variables?.action === a.value ? t('review.saving') : t(`review.action.${a.key}`)}
                </button>
              ))}
            </div>
            {act.isError && (
              <p role="alert" className="flex gap-1 text-danger-fg">
                <span aria-hidden="true">✕</span> {t(errorMessageKey(act.error))}
              </p>
            )}
            <p className="text-ink-muted">{t('review.noAuto')}</p>
          </section>
        </div>
      )}
    </dialog>
  );
}
