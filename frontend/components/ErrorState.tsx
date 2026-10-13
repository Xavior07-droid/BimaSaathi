'use client';
// F25: one error pattern for every screen: what went wrong in plain words + a Try again button.
import { useTranslation } from 'react-i18next';
import { errorMessageKey } from '@/lib/errors';

interface Props {
  error?: unknown;
  title?: string; // already translated; optional heading above the message
  onRetry?: () => void;
  retrying?: boolean;
}

export default function ErrorState({ error, title, onRetry, retrying }: Props) {
  const { t } = useTranslation();
  return (
    <div role="alert" className="card space-y-3 border-danger-line bg-danger-bg text-danger-fg">
      {title && <h2>{title}</h2>}
      <p className="flex gap-2 font-medium">
        <span aria-hidden="true">✕</span>
        <span>{t(errorMessageKey(error))}</span>
      </p>
      {onRetry && (
        <button type="button" className="btn-secondary w-full" onClick={onRetry} disabled={retrying}>
          {retrying ? t('common.loading') : t('common.retry')}
        </button>
      )}
    </div>
  );
}
