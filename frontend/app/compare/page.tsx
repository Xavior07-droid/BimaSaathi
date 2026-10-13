'use client';
// F20: Compare. Choose 2-3 policies, set a hospital-stay scenario, see a side-by-side table.
// F21: out-of-pocket cards (lowest first), best-fit badge, "how calculated", "simplified estimate".
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import CompareTable from '@/components/CompareTable';
import EmptyState from '@/components/EmptyState';
import ErrorState from '@/components/ErrorState';
import LoadingState from '@/components/LoadingState';
import OopCard from '@/components/OopCard';
import { useCurrentPolicyId } from '@/lib/currentPolicy';
import { errorMessageKey } from '@/lib/errors';
import { formatDate, formatInr } from '@/lib/format';
import { useCompare, usePolicies } from '@/lib/queries';
import type { CompareResponse, Scenario } from '@/lib/types';
import { validateScenario, type ScenarioErrors, type ScenarioValues } from '@/lib/validate';

const MIN_POLICIES = 2;
const MAX_POLICIES = 3;
const DEFAULTS: ScenarioValues = { days: '3', rent: '5000', bill: '100000' };

function FieldError({ id, k }: { id: string; k?: string }) {
  const { t } = useTranslation();
  if (!k) return null;
  return (
    <p id={id} role="alert" className="mt-1 flex gap-1 text-danger-fg">
      <span aria-hidden="true">⚠</span> {t(k)}
    </p>
  );
}

interface NumFieldProps {
  id: string;
  label: string;
  help: string;
  value: string;
  error?: string;
  prefix?: string;
  maxLen: number;
  onChange: (v: string) => void;
}

function NumField({ id, label, help, value, error, prefix, maxLen, onChange }: NumFieldProps) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-lg font-semibold">
        {label}
      </label>
      <p className="mb-2 text-ink-soft">{help}</p>
      <div className="relative">
        {prefix && (
          <span aria-hidden="true" className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-ink-soft">
            {prefix}
          </span>
        )}
        <input
          id={id}
          type="text"
          inputMode="numeric"
          pattern="[0-9]*"
          autoComplete="off"
          className={`input ${prefix ? 'pl-9' : ''}`}
          value={value}
          onChange={(e) => onChange(e.target.value.replace(/\D/g, '').slice(0, maxLen))}
          aria-invalid={!!error}
          aria-describedby={error ? `${id}-err` : undefined}
        />
      </div>
      <FieldError id={`${id}-err`} k={error} />
    </div>
  );
}

export default function ComparePage() {
  const { t } = useTranslation();
  const policies = usePolicies();
  const current = useCurrentPolicyId();
  const compare = useCompare();

  const [selected, setSelected] = useState<string[]>([]);
  const [scenario, setScenario] = useState<ScenarioValues>(DEFAULTS);
  const [errors, setErrors] = useState<ScenarioErrors>({});
  const [pickError, setPickError] = useState(false);
  const [result, setResult] = useState<{ data: CompareResponse; scenario: Scenario } | null>(null);
  const resultRef = useRef<HTMLHeadingElement>(null);
  const preselected = useRef(false);

  // Start with the policy the user is working on already ticked (once, after the list loads).
  useEffect(() => {
    if (preselected.current || !policies.data || !current) return;
    preselected.current = true;
    if (policies.data.some((p) => p.policy_id === current)) setSelected([current]);
  }, [policies.data, current]);

  const toggle = (id: string) => {
    setPickError(false);
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : s.length >= MAX_POLICIES ? s : [...s, id]));
  };

  const setField = (k: keyof ScenarioValues) => (v: string) => {
    setScenario((s) => ({ ...s, [k]: v }));
    if (errors[k]) setErrors((e) => ({ ...e, [k]: undefined }));
  };

  const run = (e: React.FormEvent) => {
    e.preventDefault();
    const errs = validateScenario(scenario);
    const tooFew = selected.length < MIN_POLICIES;
    setErrors(errs);
    setPickError(tooFew);
    if (tooFew) {
      document.getElementById('compare-pick')?.focus();
      return;
    }
    const first = (['days', 'rent', 'bill'] as const).find((k) => errs[k]);
    if (first) {
      document.getElementById(`compare-${first}`)?.focus();
      return;
    }
    const sc: Scenario = { days: Number(scenario.days), room_rent_per_day: Number(scenario.rent), bill: Number(scenario.bill) };
    compare.mutate(
      { policy_ids: selected, scenario: sc },
      {
        onSuccess: (data) => {
          setResult({ data, scenario: sc });
          setTimeout(() => {
            resultRef.current?.focus();
            resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }, 0);
        },
      },
    );
  };

  if (policies.isLoading) return <LoadingState cards={2} />;

  if (policies.isError) {
    return (
      <div className="space-y-3">
        <h1>{t('compare.title')}</h1>
        <ErrorState error={policies.error} onRetry={() => void policies.refetch()} retrying={policies.isRefetching} />
      </div>
    );
  }

  const list = policies.data ?? [];
  if (list.length < MIN_POLICIES) {
    return (
      <EmptyState
        icon="compare"
        title={t('compare.needTwoTitle')}
        body={t('compare.needTwoBody', { count: list.length })}
        action={{ label: t('processing.goHome'), href: '/' }}
      />
    );
  }

  const full = selected.length >= MAX_POLICIES;
  // Lowest out-of-pocket first (numbers come from the backend calculator).
  const sortedOutcomes = result ? [...result.data.outcomes].sort((a, b) => a.out_of_pocket - b.out_of_pocket) : [];

  return (
    <div className="space-y-6">
      <form onSubmit={run} noValidate className="space-y-5" aria-labelledby="compare-h">
        <div>
          <h1 id="compare-h">{t('compare.title')}</h1>
          <p className="mt-1 text-ink-soft">{t('compare.subtitle')}</p>
        </div>

        {/* Policy selector */}
        <fieldset className="card space-y-3" aria-describedby={pickError ? 'err-pick' : undefined}>
          <legend className="px-1 text-lg font-semibold">{t('compare.pickTitle')}</legend>
          <p className="text-ink-soft">{t('compare.pickHelp', { min: MIN_POLICIES, max: MAX_POLICIES })}</p>
          <ul className="space-y-3">
            {list.map((p, i) => {
              const checked = selected.includes(p.policy_id);
              const blocked = full && !checked;
              return (
                <li key={p.policy_id}>
                  <label
                    className={`flex min-h-touch gap-3 rounded-card border p-3 ${
                      blocked ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'
                    } ${checked ? 'border-brand-700 bg-brand-50' : 'border-surface-line bg-surface'}`}
                  >
                    <input
                      id={i === 0 ? 'compare-pick' : undefined}
                      type="checkbox"
                      checked={checked}
                      disabled={blocked}
                      onChange={() => toggle(p.policy_id)}
                      className="mt-1 h-5 w-5 shrink-0 accent-brand-700"
                    />
                    <span className="min-w-0">
                      <span className="block font-semibold">{p.insurer ?? t('common.unknown')}</span>
                      <span className="block text-ink-soft">
                        {t('policy.sumInsured')}: {formatInr(p.sum_insured)}
                      </span>
                      <span className="block text-ink-soft">
                        {t('policy.renewalDate')}: {formatDate(p.renewal_date)}
                      </span>
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
          <p className="font-semibold text-ink-soft" aria-live="polite">
            {t('compare.chosen', { count: selected.length, max: MAX_POLICIES })}
            {full && ` · ${t('compare.maxReached', { max: MAX_POLICIES })}`}
          </p>
          <FieldError id="err-pick" k={pickError ? 'compare.errPick' : undefined} />
        </fieldset>

        {/* Scenario */}
        <fieldset className="card space-y-4">
          <legend className="px-1 text-lg font-semibold">{t('compare.scenarioTitle')}</legend>
          <p className="text-ink-soft">{t('compare.scenarioHelp')}</p>
          <NumField
            id="compare-days"
            label={t('compare.days')}
            help={t('compare.daysHelp')}
            value={scenario.days}
            error={errors.days}
            maxLen={3}
            onChange={setField('days')}
          />
          <NumField
            id="compare-rent"
            label={t('compare.rent')}
            help={t('compare.rentHelp')}
            value={scenario.rent}
            error={errors.rent}
            prefix="₹"
            maxLen={7}
            onChange={setField('rent')}
          />
          <NumField
            id="compare-bill"
            label={t('compare.bill')}
            help={t('compare.billHelp')}
            value={scenario.bill}
            error={errors.bill}
            prefix="₹"
            maxLen={9}
            onChange={setField('bill')}
          />
        </fieldset>

        {compare.isError && (
          <p role="alert" className="rounded-card border border-danger-line bg-danger-bg p-3 font-medium text-danger-fg">
            ✕ {t(errorMessageKey(compare.error))}
          </p>
        )}

        <button type="submit" className="btn-primary btn-lg w-full" disabled={compare.isPending}>
          {compare.isPending ? (
            <>
              <span aria-hidden="true" className="inline-block h-5 w-5 rounded-full border-2 border-current border-t-transparent motion-safe:animate-spin" />
              {t('compare.running')}
            </>
          ) : (
            t('compare.run')
          )}
        </button>
      </form>

      {result && (
        <div className="space-y-6">
          <section className="space-y-3" aria-labelledby="compare-result-h">
            <h2 id="compare-result-h" ref={resultRef} tabIndex={-1}>
              {t('compare.oopTitle')}
            </h2>
            <p className="flex flex-wrap gap-2">
              <span className="chip-info font-semibold">
                <span aria-hidden="true">≈</span> {t('compare.estimate')}
              </span>
              <span className="chip-neutral">{t('compare.stay', { count: result.scenario.days })}</span>
              <span className="chip-neutral">{t('compare.rentChip', { amount: formatInr(result.scenario.room_rent_per_day) })}</span>
              <span className="chip-neutral">{t('compare.billChip', { amount: formatInr(result.scenario.bill) })}</span>
            </p>
            <ul className="space-y-3">
              {sortedOutcomes.map((o) => (
                <OopCard
                  key={o.policy_id}
                  outcome={o}
                  insurer={result.data.rows.find((r) => r.policy_id === o.policy_id)?.insurer ?? null}
                  bill={result.scenario.bill}
                  isBest={o.policy_id === result.data.best_policy_id}
                />
              ))}
            </ul>
            <p className="text-ink-muted">{t('compare.estimateNote')}</p>
          </section>

          {result.data.recommendation && (
            <section className="card space-y-2 border-brand-300" aria-labelledby="advice-h">
              <h2 id="advice-h">{t('compare.adviceTitle')}</h2>
              <p>{result.data.recommendation}</p>
              <p className="text-ink-muted">{t('compare.adviceNote')}</p>
            </section>
          )}

          <section className="space-y-3" aria-labelledby="table-h">
            <h2 id="table-h">{t('compare.tableTitle')}</h2>
            <CompareTable rows={result.data.rows} />
          </section>
        </div>
      )}
    </div>
  );
}
