'use client';
import { useTranslation } from 'react-i18next';
import Icon from './Icon';

/** The free-tier privacy warning. Shown on the consent screen and next to uploads (F8). */
export default function PrivacyWarning({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation();
  return (
    <div role="note" className="rounded-card border border-warning-line bg-warning-bg p-4 text-warning-fg">
      <p className="flex items-center gap-2 font-semibold">
        <Icon name="info" className="h-5 w-5 shrink-0" />
        {t('consent.privacyTitle')}
      </p>
      <p className="mt-2">{t('disclaimer.privacy')}</p>
      {!compact && <p className="mt-2">{t('consent.anonymise')}</p>}
    </div>
  );
}
