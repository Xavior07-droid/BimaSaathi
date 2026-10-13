'use client';
// F25: last-resort screen if a page crashes while rendering. The header and tab bar stay usable.
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';

export default function RouteError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const { t } = useTranslation();
  useEffect(() => {
    console.error(error); // for developers only: nothing technical is shown to the user
  }, [error]);
  return (
    <div role="alert" className="card space-y-3 border-danger-line bg-danger-bg text-danger-fg">
      <h2>{t('errors.crashTitle')}</h2>
      <p>{t('errors.crashBody')}</p>
      <button type="button" className="btn-primary w-full" onClick={reset}>
        {t('common.retry')}
      </button>
    </div>
  );
}
