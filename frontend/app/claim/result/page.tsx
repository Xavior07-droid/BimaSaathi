'use client';
// F19: Claim result. Score ring, top 3 "do this first" actions, document checklist
// (found / missing / unclear), policy rule checks with page + clause, and share.
import { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useTranslation } from 'react-i18next';
import ChecklistChip from '@/components/ChecklistChip';
import EmptyState from '@/components/EmptyState';
import Icon from '@/components/Icon';
import LoadingState from '@/components/LoadingState';
import ScoreRing from '@/components/ScoreRing';
import { clearClaimDraft } from '@/lib/claimDraft';
import { clearClaimResult, loadClaimResult, type StoredClaimResult } from '@/lib/claimResult';
import { formatDate } from '@/lib/format';
import { usePolicy } from '@/lib/queries';
import type { DocStatus, RuleStatus } from '@/lib/types';

const DOC_ORDER: Record<DocStatus, number> = { missing: 0, unclear: 1, found: 2 };
const RULE_ORDER: Record<RuleStatus, number> = { fail: 0, at_risk: 1, pass: 2 };

function Result({ data }: { data: StoredClaimResult }) {
  const { t } = useTranslation();
  const { result } = data;
  const policy = usePolicy(data.policyId);
  const [shareNote, setShareNote] = useState<'copied' | 'failed' | null>(null);

  const actions = result.top_actions.slice(0, 3);
  const docs = [...result.documents].sort((a, b) => DOC_ORDER[a.status] - DOC_ORDER[b.status]);
  const rules = [...result.rules].sort((a, b) => RULE_ORDER[a.status] - RULE_ORDER[b.status]);
  const score = Math.max(0, Math.min(100, Math.round(result.score)));

  const share = async () => {
    setShareNote(null);
    // Only the score and the to-do list are shared: no name, diagnosis, amounts or documents.
    const text = [
      t('claim.result.shareText', { score }),
      ...actions.map((a, i) => `${i + 1}. ${a}`),
      t('claim.result.notGuarantee'),
    ].join('\n');
    try {
      if (typeof navigator.share === 'function') {
        await navigator.share({ title: t('claim.result.title'), text });
        return;
      }
      await navigator.clipboard.writeText(text);
      setShareNote('copied');
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return; // user closed the share sheet
      try {
        await navigator.clipboard.writeText(text);
        setShareNote('copied');
      } catch {
        setShareNote('failed');
      }
    }
  };

  return (
    <div className="space-y-5">
      <header>
        <h1>{t('claim.result.title')}</h1>
        <p className="mt-2 flex flex-wrap gap-2">
          {policy.data?.insurer && (
            <span className="chip-neutral">
              {t('claim.checkingAgainst')}: {policy.data.insurer}
            </span>
          )}
          <span className="chip-neutral">{formatDate(data.checkedAt)}</span>
        </p>
      </header>

      <section className="card flex flex-col items-center gap-3" aria-labelledby="score-h">
        <h2 id="score-h">{t('claim.result.scoreTitle')}</h2>
        <ScoreRing score={score} />
        <p className="text-center text-ink-soft">{t('claim.result.scoreHelp')}</p>
      </section>

      <section className="card space-y-3 border-brand-300" aria-labelledby="act-h">
        <h2 id="act-h">{t('claim.result.actionsTitle')}</h2>
        {actions.length === 0 ? (
          <p className="chip-success">
            <span aria-hidden="true">✓</span> {t('claim.result.noActions')}
          </p>
        ) : (
          <ol className="space-y-3">
            {actions.map((a, i) => (
              <li key={i} className="flex items-start gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-700 font-bold text-white">
                  {i + 1}
                </span>
                <span className="pt-1 font-medium">{a}</span>
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="card space-y-3" aria-labelledby="docs-h">
        <h2 id="docs-h">{t('claim.result.docsTitle')}</h2>
        {docs.length === 0 ? (
          <p className="text-ink-soft">{t('claim.result.noDocs')}</p>
        ) : (
          <ul className="space-y-3">
            {docs.map((d, i) => (
              <li key={i} className="rounded-card border border-surface-line p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-semibold">{d.doc_type}</p>
                  <ChecklistChip status={d.status} />
                </div>
                {d.issues.length > 0 && (
                  <ul className="mt-2 list-disc space-y-1 pl-6 text-ink-soft">
                    {d.issues.map((iss, j) => (
                      <li key={j}>{iss}</li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card space-y-3" aria-labelledby="rules-h">
        <h2 id="rules-h">{t('claim.result.rulesTitle')}</h2>
        <p className="text-ink-muted">{t('claim.result.rulesHelp')}</p>
        <ul className="space-y-3">
          {rules.map((r) => (
            <li key={r.rule_id} className="rounded-card border border-surface-line p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-semibold">{t(`claim.result.rules.${r.rule_id}`)}</p>
                <ChecklistChip status={r.status} />
              </div>
              <p className="mt-2 text-ink-soft">{r.reason}</p>
              {r.clause && (
                <p className="mt-1 text-ink-muted">{t('common.source', { page: r.clause.page, clause: r.clause.clause })}</p>
              )}
            </li>
          ))}
        </ul>
      </section>

      <p className="flex gap-2 rounded-card border border-info-line bg-info-bg p-3 font-medium text-info-fg">
        <Icon name="info" className="mt-0.5 h-5 w-5 shrink-0" />
        <span>{t('claim.result.notGuarantee')}</span>
      </p>

      <div className="grid gap-3">
        <button type="button" className="btn-primary btn-lg w-full" onClick={() => void share()}>
          {t('claim.result.share')}
        </button>
        {shareNote && (
          <p role="status" className={`text-center font-medium ${shareNote === 'copied' ? 'text-success-fg' : 'text-danger-fg'}`}>
            {shareNote === 'copied' ? `✓ ${t('claim.result.copied')}` : `✕ ${t('claim.result.shareFailed')}`}
          </p>
        )}
        <Link href={`/claim?id=${encodeURIComponent(data.policyId)}`} className="btn-secondary w-full">
          {t('claim.result.checkAgain')}
        </Link>
        <Link
          href="/claim"
          className="btn-ghost w-full"
          onClick={() => {
            clearClaimResult();
            clearClaimDraft();
          }}
        >
          {t('claim.result.newClaim')}
        </Link>
      </div>
    </div>
  );
}

function ResultRoute() {
  const { t } = useTranslation();
  const fromUrl = useSearchParams().get('id');
  const [data, setData] = useState<StoredClaimResult | null | undefined>(undefined); // undefined = not loaded yet

  // sessionStorage is not available during static export, so read it after mount.
  useEffect(() => {
    setData(loadClaimResult());
  }, []);

  if (data === undefined) return <LoadingState />;
  if (!data || (fromUrl && data.policyId !== fromUrl)) {
    return (
      <EmptyState
        icon="claim"
        title={t('claim.result.emptyTitle')}
        body={t('claim.result.emptyBody')}
        action={{ label: t('claim.result.startCheck'), href: fromUrl ? `/claim?id=${encodeURIComponent(fromUrl)}` : '/claim' }}
      />
    );
  }
  return <Result data={data} />;
}

export default function ClaimResultPage() {
  return (
    <Suspense fallback={null}>
      <ResultRoute />
    </Suspense>
  );
}
