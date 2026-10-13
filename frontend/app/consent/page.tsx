'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useTranslation } from 'react-i18next';
import PrivacyWarning from '@/components/PrivacyWarning';
import { useAuth } from '@/lib/auth';

export default function ConsentPage() {
  const { t } = useTranslation();
  const router = useRouter();
  const { acceptConsent, busy, consented } = useAuth();
  const [agreed, setAgreed] = useState(false);

  const accept = async () => {
    await acceptConsent();
    router.replace('/');
  };

  return (
    <div className="space-y-4">
      <h1>{t('consent.title')}</h1>
      <PrivacyWarning />
      <ul className="card list-disc space-y-3 pl-9 pr-4">
        <li>{t('consent.p1')}</li>
        <li>{t('consent.p2')}</li>
        <li>{t('consent.p3')}</li>
      </ul>

      {consented ? (
        <p className="chip-success">✓ {t('consent.done')}</p>
      ) : (
        <>
          <label className="flex min-h-touch cursor-pointer items-start gap-3 rounded-card border border-surface-line bg-surface p-4">
            <input
              type="checkbox"
              checked={agreed}
              onChange={(e) => setAgreed(e.target.checked)}
              className="mt-1 h-6 w-6 shrink-0 accent-brand-700"
            />
            <span>{t('consent.agree')}</span>
          </label>
          <button type="button" disabled={!agreed || busy} onClick={() => void accept()} className="btn-primary btn-lg w-full">
            {busy ? t('consent.saving') : t('consent.accept')}
          </button>
        </>
      )}
    </div>
  );
}
