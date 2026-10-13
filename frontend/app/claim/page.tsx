'use client';
// F17: Claim Checker intake form (type, admission date, diagnosis, estimated bill).
// F18: step 2 = document photo grid (previews, max 8, client-side compress). F19 shows the result.
import { Suspense, useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useTranslation } from 'react-i18next';
import EmptyState from '@/components/EmptyState';
import UploadGrid from '@/components/UploadGrid';
import { clearClaimDraft, loadClaimDraft, saveClaimDraft } from '@/lib/claimDraft';
import { saveClaimResult } from '@/lib/claimResult';
import { useCurrentPolicyId } from '@/lib/currentPolicy';
import { errorMessageKey } from '@/lib/errors';
import { formatDate, formatInr } from '@/lib/format';
import { useClaimCheck, usePolicy } from '@/lib/queries';
import { useClaimDocs } from '@/lib/useClaimDocs';
import { validateClaimForm, type ClaimFormErrors, type ClaimFormValues } from '@/lib/validate';

const EMPTY: ClaimFormValues = { claimType: '', admissionDate: '', diagnosis: '', bill: '' };
// Shown when the policy does not list its own required documents (keys under claim.defaultDocs).
const DEFAULT_DOCS = ['claimForm', 'discharge', 'bills', 'prescriptions', 'idProof'] as const;

function FieldError({ id, k }: { id: string; k?: string }) {
  const { t } = useTranslation();
  if (!k) return null;
  return (
    <p id={id} role="alert" className="mt-1 flex gap-1 text-danger-fg">
      <span aria-hidden="true">⚠</span> {t(k)}
    </p>
  );
}

function ClaimFlow({ policyId }: { policyId: string }) {
  const { t } = useTranslation();
  const router = useRouter();
  const policy = usePolicy(policyId);
  const grid = useClaimDocs();
  const check = useClaimCheck();
  const [values, setValues] = useState<ClaimFormValues>(EMPTY);
  const [errors, setErrors] = useState<ClaimFormErrors>({});
  const [step, setStep] = useState<'form' | 'docs'>('form');
  const summaryRef = useRef<HTMLDivElement>(null);

  // Restore saved details after mount (sessionStorage is not available during static export).
  useEffect(() => {
    const d = loadClaimDraft();
    if (d) setValues(d);
  }, []);

  const set = <K extends keyof ClaimFormValues>(k: K, v: ClaimFormValues[K]) => {
    setValues((s) => ({ ...s, [k]: v }));
    if (errors[k]) setErrors((e) => ({ ...e, [k]: undefined }));
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const errs = validateClaimForm(values);
    setErrors(errs);
    if (Object.keys(errs).length > 0) {
      // Move focus to the first problem so keyboard / screen-reader users land on it.
      const first = (['claimType', 'admissionDate', 'diagnosis', 'bill'] as const).find((k) => errs[k]);
      document.getElementById(first === 'claimType' ? 'claim-type-cashless' : `claim-${first}`)?.focus();
      return;
    }
    saveClaimDraft({ ...values, diagnosis: values.diagnosis.trim() });
    setStep('docs');
    setTimeout(() => summaryRef.current?.focus(), 0);
  };

  const reset = () => {
    clearClaimDraft();
    grid.clear();
    check.reset();
    setValues(EMPTY);
    setErrors({});
    setStep('form');
  };

  const billNum = Number(values.bill);
  const types = ['cashless', 'reimbursement'] as const;

  const submitDocs = () => {
    if (!values.claimType || grid.files.length === 0 || grid.isWorking) return;
    check.mutate(
      {
        policy_id: policyId,
        claim_type: values.claimType,
        admission_date: values.admissionDate,
        diagnosis: values.diagnosis.trim(),
        estimated_bill: billNum,
        documents: grid.files,
      },
      {
        onSuccess: (result) => {
          saveClaimResult(policyId, result);
          router.push(`/claim/result?id=${encodeURIComponent(policyId)}`);
        },
      },
    );
  };

  // Documents this policy asks for (from the Policy Brain), else our default list.
  const fromPolicy = values.claimType ? policy.data?.claim_requirements?.[values.claimType] ?? [] : [];
  const neededDocs = fromPolicy.length > 0 ? fromPolicy : DEFAULT_DOCS.map((k) => t(`claim.defaultDocs.${k}`));

  if (step === 'docs') {
    return (
      <div className="space-y-4">
        <h1>{t('claim.title')}</h1>
        <div ref={summaryRef} tabIndex={-1} className="card space-y-3">
          <h2>{t('claim.yourDetails')}</h2>
          <dl className="space-y-2">
            <div><dt className="text-ink-muted">{t('claim.type')}</dt><dd className="font-semibold">{t(`claim.types.${values.claimType || 'cashless'}`)}</dd></div>
            <div><dt className="text-ink-muted">{t('claim.admissionDate')}</dt><dd className="font-semibold">{formatDate(values.admissionDate)}</dd></div>
            <div><dt className="text-ink-muted">{t('claim.diagnosis')}</dt><dd className="font-semibold">{values.diagnosis.trim()}</dd></div>
            <div><dt className="text-ink-muted">{t('claim.bill')}</dt><dd className="font-semibold">{formatInr(billNum)}</dd></div>
          </dl>
          <button type="button" className="btn-secondary w-full" onClick={() => setStep('form')}>
            {t('claim.edit')}
          </button>
        </div>
        {neededDocs.length > 0 && (
          <details className="card">
            <summary className="min-h-touch cursor-pointer py-2 text-lg font-semibold">{t('claim.neededTitle')}</summary>
            <ul className="mt-2 list-disc space-y-1 pl-6 text-ink-soft">
              {neededDocs.map((d) => (
                <li key={d}>{d}</li>
              ))}
            </ul>
          </details>
        )}

        <UploadGrid
          docs={grid.docs}
          max={grid.max}
          notices={grid.notices}
          disabled={check.isPending}
          onAdd={(f) => void grid.addFiles(f)}
          onRemove={grid.remove}
        />

        {check.isError && (
          <p role="alert" className="rounded-card border border-danger-line bg-danger-bg p-3 font-medium text-danger-fg">
            ✕ {t(errorMessageKey(check.error))}
          </p>
        )}

        <button
          type="button"
          className="btn-primary btn-lg w-full"
          onClick={submitDocs}
          disabled={grid.files.length === 0 || grid.isWorking || check.isPending}
        >
          {check.isPending ? (
            <>
              <span aria-hidden="true" className="inline-block h-5 w-5 rounded-full border-2 border-current border-t-transparent motion-safe:animate-spin" />
              {t('claim.checking')}
            </>
          ) : (
            t('claim.checkNow')
          )}
        </button>
        {grid.files.length === 0 && !grid.isWorking && <p className="text-center text-ink-muted">{t('claim.needOne')}</p>}
        <button type="button" className="btn-ghost w-full" onClick={reset} disabled={check.isPending}>
          {t('claim.startOver')}
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-5" aria-labelledby="claim-h">
      <div>
        <h1 id="claim-h">{t('claim.title')}</h1>
        <p className="mt-1 text-ink-soft">{t('claim.subtitle')}</p>
        {policy.data?.insurer && (
          <p className="mt-2 chip-neutral">
            {t('claim.checkingAgainst')}: {policy.data.insurer}
          </p>
        )}
      </div>

      {/* Claim type */}
      <fieldset className="card space-y-3" aria-describedby={errors.claimType ? 'err-type' : undefined}>
        <legend className="px-1 text-lg font-semibold">{t('claim.type')}</legend>
        {types.map((ty) => {
          const checked = values.claimType === ty;
          return (
            <label
              key={ty}
              className={`flex min-h-touch cursor-pointer gap-3 rounded-card border p-3 ${
                checked ? 'border-brand-700 bg-brand-50' : 'border-surface-line bg-surface'
              }`}
            >
              <input
                id={`claim-type-${ty}`}
                type="radio"
                name="claimType"
                value={ty}
                checked={checked}
                onChange={() => set('claimType', ty)}
                className="mt-1 h-5 w-5 accent-brand-700"
              />
              <span>
                <span className="block font-semibold">{t(`claim.types.${ty}`)}</span>
                <span className="block text-ink-soft">{t(`claim.typeHelp.${ty}`)}</span>
              </span>
            </label>
          );
        })}
        <FieldError id="err-type" k={errors.claimType} />
      </fieldset>

      {/* Admission date */}
      <div>
        <label htmlFor="claim-admissionDate" className="mb-1 block text-lg font-semibold">
          {t('claim.admissionDate')}
        </label>
        <p className="mb-2 text-ink-soft">{t('claim.admissionHelp')}</p>
        <input
          id="claim-admissionDate"
          type="date"
          className="input"
          value={values.admissionDate}
          onChange={(e) => set('admissionDate', e.target.value)}
          aria-invalid={!!errors.admissionDate}
          aria-describedby={errors.admissionDate ? 'err-date' : undefined}
        />
        <FieldError id="err-date" k={errors.admissionDate} />
      </div>

      {/* Diagnosis */}
      <div>
        <label htmlFor="claim-diagnosis" className="mb-1 block text-lg font-semibold">
          {t('claim.diagnosis')}
        </label>
        <p className="mb-2 text-ink-soft">{t('claim.diagnosisHelp')}</p>
        <input
          id="claim-diagnosis"
          type="text"
          className="input"
          maxLength={200}
          autoComplete="off"
          value={values.diagnosis}
          onChange={(e) => set('diagnosis', e.target.value)}
          placeholder={t('claim.diagnosisPlaceholder')}
          aria-invalid={!!errors.diagnosis}
          aria-describedby={errors.diagnosis ? 'err-dx' : undefined}
        />
        <FieldError id="err-dx" k={errors.diagnosis} />
      </div>

      {/* Estimated bill */}
      <div>
        <label htmlFor="claim-bill" className="mb-1 block text-lg font-semibold">
          {t('claim.bill')}
        </label>
        <p className="mb-2 text-ink-soft">{t('claim.billHelp')}</p>
        <div className="relative">
          <span aria-hidden="true" className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-ink-soft">
            ₹
          </span>
          <input
            id="claim-bill"
            type="text"
            inputMode="numeric"
            pattern="[0-9]*"
            autoComplete="off"
            className="input pl-9"
            value={values.bill}
            onChange={(e) => set('bill', e.target.value.replace(/\D/g, '').slice(0, 9))}
            aria-invalid={!!errors.bill}
            aria-describedby={errors.bill ? 'err-bill' : 'bill-preview'}
          />
        </div>
        {values.bill && Number(values.bill) > 0 && (
          <p id="bill-preview" className="mt-1 text-ink-soft">
            {formatInr(Number(values.bill))}
          </p>
        )}
        <FieldError id="err-bill" k={errors.bill} />
      </div>

      <button type="submit" className="btn-primary btn-lg w-full">
        {t('claim.next')}
      </button>
    </form>
  );
}

function ClaimRoute() {
  const { t } = useTranslation();
  const fromUrl = useSearchParams().get('id');
  const remembered = useCurrentPolicyId();
  const id = fromUrl ?? remembered;
  if (!id) {
    return (
      <EmptyState
        icon="claim"
        title={t('claim.noPolicyTitle')}
        body={t('claim.noPolicyBody')}
        action={{ label: t('processing.goHome'), href: '/' }}
      />
    );
  }
  return <ClaimFlow policyId={id} />;
}

export default function ClaimPage() {
  return (
    <Suspense fallback={null}>
      <ClaimRoute />
    </Suspense>
  );
}
