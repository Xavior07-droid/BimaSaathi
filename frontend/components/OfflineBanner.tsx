'use client';
// F25: tells the person when the phone has no internet, instead of screens failing one by one.
import { useTranslation } from 'react-i18next';
import { useOnline } from '@/lib/useOnline';

export default function OfflineBanner() {
  const { t } = useTranslation();
  const online = useOnline();
  if (online) return null;
  return (
    <div role="status" aria-live="polite" className="mb-4 rounded-card border border-warning-line bg-warning-bg p-3 font-medium text-warning-fg">
      <span aria-hidden="true">⚠</span> {t('errors.offline')}
    </div>
  );
}
