'use client';
// F24: Settings. Account, language, notifications shortcut, privacy, "Delete my data", insurer demo link.
import { useState } from 'react';
import Link from 'next/link';
import { useTranslation } from 'react-i18next';
import DeleteDataDialog from '@/components/DeleteDataDialog';
import InstallCard from '@/components/InstallCard';
import LanguageSwitcher from '@/components/LanguageSwitcher';
import PrivacyWarning from '@/components/PrivacyWarning';
import { useAuth } from '@/lib/auth';

export default function SettingsPage() {
  const { t } = useTranslation();
  const { user, signOut } = useAuth();
  const [confirmOpen, setConfirmOpen] = useState(false);

  return (
    <div className="space-y-5">
      <h1>{t('nav.settings')}</h1>

      <section className="card space-y-3" aria-labelledby="acc-h">
        <h2 id="acc-h">{t('settings.accountTitle')}</h2>
        <p className="break-words">{t('auth.signedInAs', { name: user?.email ?? user?.name ?? '' })}</p>
        {user?.demo && (
          <p className="chip-info">
            <span aria-hidden="true">ℹ</span> {t('auth.demoBadge')}
          </p>
        )}
        <button type="button" onClick={() => void signOut()} className="btn-secondary w-full">
          {t('auth.signOut')}
        </button>
      </section>

      <section className="card space-y-3" aria-labelledby="lang-h">
        <h2 id="lang-h">{t('lang.label')}</h2>
        <p className="text-ink-soft">{t('settings.languageHelp')}</p>
        <LanguageSwitcher className="w-full justify-between" />
      </section>

      <section className="card space-y-3" aria-labelledby="notif-h">
        <h2 id="notif-h">{t('settings.notificationsTitle')}</h2>
        <p className="text-ink-soft">{t('settings.notificationsBody')}</p>
        <Link href="/renewals" className="btn-secondary w-full">
          {t('settings.notificationsLink')}
        </Link>
      </section>

      <InstallCard />

      <section className="space-y-3" aria-labelledby="priv-h">
        <h2 id="priv-h">{t('settings.privacyTitle')}</h2>
        <PrivacyWarning />
        <p className="text-ink-soft">{t('settings.privacyKeeps')}</p>
      </section>

      <section className="card space-y-3 border-danger-line" aria-labelledby="data-h">
        <h2 id="data-h">{t('settings.dataTitle')}</h2>
        <p className="text-ink-soft">{t('settings.deleteHelp')}</p>
        <button
          type="button"
          onClick={() => setConfirmOpen(true)}
          className="min-h-touch w-full rounded-card border-2 border-danger-solid bg-surface px-4 font-semibold text-danger-fg"
        >
          {t('settings.deleteBtn')}
        </button>
      </section>

      <section className="card space-y-3" aria-labelledby="ins-h">
        <h2 id="ins-h">{t('settings.insurerTitle')}</h2>
        <p className="text-ink-soft">{t('settings.insurerBody')}</p>
        <Link href="/review" className="btn-secondary w-full">
          {t('shell.insurerView')}
        </Link>
      </section>

      <DeleteDataDialog open={confirmOpen} onClose={() => setConfirmOpen(false)} />
    </div>
  );
}
