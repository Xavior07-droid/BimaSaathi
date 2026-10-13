'use client';
import { Suspense, useEffect } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useTranslation } from 'react-i18next';
import AuthGate from './AuthGate';
import Disclaimer from './Disclaimer';
import Icon from './Icon';
import LanguageSwitcher from './LanguageSwitcher';
import Nav from './Nav';
import OfflineBanner from './OfflineBanner';
import ServerWaking from './ServerWaking';
import '@/lib/pwaInstall'; // starts listening for the browser's install prompt right away
import { useServerStatus } from '@/lib/serverStatus';
import { useAuth } from '@/lib/auth';
import { rememberPolicyId } from '@/lib/currentPolicy';

/** Remembers ?id= from the URL. Isolated in its own Suspense boundary (required for static export). */
function PolicyIdSync() {
  const id = useSearchParams().get('id');
  useEffect(() => {
    if (id) rememberPolicyId(id);
  }, [id]);
  return null;
}

/** Header + content + disclaimer footer + bottom tab bar, used on every screen. */
export default function AppShell({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation();
  const server = useServerStatus();
  const { user, consented } = useAuth();
  const ready = !!user && consented; // tab bar + settings only after sign-in and consent
  return (
    <>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded-card focus:bg-surface focus:p-3"
      >
        {t('shell.skip')}
      </a>
      <Suspense fallback={null}>
        <PolicyIdSync />
      </Suspense>

      <header className="sticky top-0 z-20 border-b border-surface-line bg-surface">
        <div className="mx-auto flex h-16 max-w-app items-center justify-between gap-2 px-3">
          <Link href="/" className="flex min-h-touch min-w-touch items-center gap-2 rounded-card text-lg font-bold text-brand-800">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-700 text-white">
              <Icon name="policy" className="h-5 w-5" />
            </span>
            <span className="max-xs:sr-only">{t('app.name')}</span>
          </Link>
          <div className="flex items-center gap-1">
            <LanguageSwitcher compact />
            {ready && (
              <Link
                href="/settings"
                aria-label={t('shell.settings')}
                className="flex min-h-touch min-w-touch items-center justify-center rounded-card text-ink-soft hover:bg-brand-50"
              >
                <Icon name="settings" />
              </Link>
            )}
          </div>
        </div>
      </header>

      <div id="main" className="min-h-[calc(100vh-4rem)] pb-[calc(theme(spacing.tab-bar)+env(safe-area-inset-bottom)+1.5rem)]">
        <div className="mx-auto w-full max-w-app px-4 pt-4">
          <OfflineBanner />
          <ServerWaking state={server.state} elapsed={server.elapsed} onRetry={server.retry} />
          <AuthGate>{children}</AuthGate>
          <Disclaimer />
        </div>
      </div>

      {ready && <Nav />}
    </>
  );
}
