'use client';
// Gate order: loading -> sign in -> consent -> app.
import { useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { useTranslation } from 'react-i18next';
import PrivacyWarning from './PrivacyWarning';
import { isFirebaseConfigured, useAuth } from '@/lib/auth';

function Spinner({ label }: { label: string }) {
  return (
    <div role="status" className="flex flex-col items-center gap-3 py-16 text-ink-soft">
      <span
        aria-hidden="true"
        className="inline-block h-8 w-8 rounded-full border-4 border-brand-200 border-t-brand-700 motion-safe:animate-spin"
      />
      {label}
    </div>
  );
}

function SignInScreen() {
  const { t } = useTranslation();
  const { signIn, signInDemo, busy, error } = useAuth();
  return (
    <div className="space-y-4">
      <div>
        <h1>{t('auth.title')}</h1>
        <p className="mt-1 text-ink-soft">{t('auth.subtitle')}</p>
      </div>

      {isFirebaseConfigured ? (
        <button type="button" onClick={() => void signIn()} disabled={busy} className="btn-primary btn-lg w-full">
          {busy ? t('auth.signingIn') : t('auth.google')}
        </button>
      ) : (
        <div className="card space-y-3">
          <p className="chip-info">{t('auth.demoBadge')}</p>
          <p>{t('auth.demoNote')}</p>
          <button type="button" onClick={signInDemo} className="btn-primary btn-lg w-full">
            {t('auth.demo')}
          </button>
        </div>
      )}

      {error && (
        <p role="alert" className="rounded-card border border-danger-line bg-danger-bg p-3 text-danger-fg">
          {t(error)}
        </p>
      )}
      <PrivacyWarning compact />
    </div>
  );
}

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation();
  const { user, loading, consented } = useAuth();
  const pathname = (usePathname() ?? '/').replace(/\/$/, '') || '/';
  const router = useRouter();
  const needsConsent = !loading && !!user && !consented && pathname !== '/consent';

  useEffect(() => {
    if (needsConsent) router.replace('/consent');
  }, [needsConsent, router]);

  if (loading) return <Spinner label={t('common.loading')} />;
  if (!user) return <SignInScreen />;
  if (needsConsent) return <Spinner label={t('common.loading')} />;
  return <>{children}</>;
}
