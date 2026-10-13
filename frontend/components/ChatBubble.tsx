'use client';
// F14: one chat message. User = right, brand colour. Assistant = left, with loading / error states.
import { useTranslation } from 'react-i18next';
import Icon from './Icon';
import type { Source } from '@/lib/types';

export type ChatMessage =
  | { id: string; role: 'user'; text: string }
  | { id: string; role: 'assistant'; status: 'loading' }
  | { id: string; role: 'assistant'; status: 'done'; text: string; grounded: boolean; citations: Source[] }
  | { id: string; role: 'assistant'; status: 'error'; errorKey: string; question: string };

export default function ChatBubble({ msg, onRetry }: { msg: ChatMessage; onRetry?: (question: string) => void }) {
  const { t } = useTranslation();

  if (msg.role === 'user') {
    return (
      <li className="flex justify-end">
        <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-card rounded-br-sm bg-brand-700 px-4 py-3 text-white">
          <span className="sr-only">{t('ask.you')}: </span>
          {msg.text}
        </p>
      </li>
    );
  }

  return (
    <li className="flex justify-start">
      <div className="max-w-[90%] rounded-card rounded-bl-sm border border-surface-line bg-surface px-4 py-3 shadow-card">
        <span className="sr-only">{t('ask.assistant')}: </span>
        {msg.status === 'loading' && (
          <p role="status" className="flex items-center gap-2 text-ink-soft">
            <span aria-hidden="true" className="flex gap-1">
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className="h-2 w-2 animate-bounce rounded-full bg-brand-600 motion-reduce:animate-none"
                  style={{ animationDelay: `${i * 150}ms` }}
                />
              ))}
            </span>
            {t('ask.thinking')}
          </p>
        )}
        {msg.status === 'done' && msg.grounded && (
          <>
            <p className="whitespace-pre-wrap break-words">{msg.text}</p>
            <div className="mt-3">
              <p className="font-medium text-ink-soft">{t('ask.sources')}</p>
              <ul className="mt-1 flex flex-wrap gap-2">
                {msg.citations.map((c, i) => (
                  <li key={i} className="chip-info">
                    <Icon name="policy" className="h-4 w-4" />
                    {t('common.source', { page: c.page, clause: c.clause })}
                  </li>
                ))}
              </ul>
            </div>
          </>
        )}
        {msg.status === 'done' && !msg.grounded && (
          // Fallback state: no grounded answer / no citation -> never show a guess.
          <div className="rounded-card border border-warning-line bg-warning-bg p-3 text-warning-fg">
            <p className="flex gap-2 font-semibold">
              <Icon name="info" className="mt-0.5 h-5 w-5 shrink-0" />
              <span>{t('ask.fallback')}</span>
            </p>
          </div>
        )}
        {msg.status === 'done' && <p className="mt-3 border-t border-surface-line pt-2 text-ink-muted">{t('ask.disclaimer')}</p>}
        {msg.status === 'error' && (
          <div role="alert" className="space-y-2 text-danger-fg">
            <p>{t(msg.errorKey)}</p>
            {onRetry && (
              <button type="button" className="btn-secondary w-full" onClick={() => onRetry(msg.question)}>
                {t('common.retry')}
              </button>
            )}
          </div>
        )}
      </div>
    </li>
  );
}
