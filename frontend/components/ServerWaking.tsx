'use client';
import { useTranslation } from 'react-i18next';
import Icon from './Icon';
import type { ServerState } from '@/lib/serverStatus';

interface Props {
  state: ServerState;
  elapsed?: number;
  onRetry?: () => void;
}

/**
 * Banner for the Render free-tier cold start.
 * - waking: spinner + message + seconds waited (polite live region)
 * - failed: error + retry button
 * Renders nothing while checking quickly or once ready.
 */
export default function ServerWaking({ state, elapsed = 0, onRetry }: Props) {
  const { t } = useTranslation();

  if (state === 'waking') {
    return (
      <div role="status" aria-live="polite" className="mb-4 rounded-card border border-info-line bg-info-bg p-4 text-info-fg">
        <p className="flex items-center gap-3 font-semibold">
          <span
            aria-hidden="true"
            className="inline-block h-5 w-5 shrink-0 rounded-full border-2 border-current border-t-transparent motion-safe:animate-spin"
          />
          {t('server.title')}
        </p>
        <p className="mt-2">{t('server.body')}</p>
        <p className="mt-2 font-medium">{t('server.elapsed', { seconds: elapsed })}</p>
      </div>
    );
  }

  if (state === 'failed') {
    return (
      <div role="alert" className="mb-4 rounded-card border border-danger-line bg-danger-bg p-4 text-danger-fg">
        <p className="flex items-center gap-2 font-semibold">
          <Icon name="info" className="h-5 w-5 shrink-0" />
          {t('server.failedTitle')}
        </p>
        <p className="mt-2">{t('server.failedBody')}</p>
        {onRetry && (
          <button type="button" onClick={onRetry} className="btn-secondary mt-3 w-full">
            {t('server.retry')}
          </button>
        )}
      </div>
    );
  }

  return null;
}
