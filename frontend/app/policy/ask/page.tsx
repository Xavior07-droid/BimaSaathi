'use client';
// F14: Ask screen (chat UI, loading, error states). Citations, chips, fallback state = F16; voice = F15.
import { Suspense, useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useTranslation } from 'react-i18next';
import ChatBubble, { type ChatMessage } from '@/components/ChatBubble';
import EmptyState from '@/components/EmptyState';
import VoiceInput from '@/components/VoiceInput';
import { errorMessageKey } from '@/lib/errors';
import { useAsk, useSuggestions } from '@/lib/queries';
import { LANGUAGES } from '@/lib/i18n';
import type { Lang } from '@/lib/types';

const MAX_LEN = 500;
let counter = 0;
const nextId = () => `m${++counter}`;

function AskChat({ id }: { id: string }) {
  const { t, i18n } = useTranslation();
  const lang = (['en', 'hi', 'mr'].includes(i18n.language) ? i18n.language : 'en') as Lang;
  const ask = useAsk(id);
  const suggestions = useSuggestions(id, lang);
  const langName = LANGUAGES.find((l) => l.code === lang)?.label ?? lang;
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLLIElement>(null);
  const baseRef = useRef(''); // text typed before the mic was pressed
  const [voice, setVoice] = useState<{ listening: boolean; errorKey: string | null }>({ listening: false, errorKey: null });

  useEffect(() => {
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    endRef.current?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'end' });
  }, [messages]);

  const send = useCallback(
    async (question: string, replaceId?: string) => {
      const q = question.trim();
      if (!q || busy) return;
      const pendingId = replaceId ?? nextId();
      setBusy(true);
      if (replaceId) {
        // Retry: turn the error bubble back into a loading bubble.
        setMessages((m) => m.map((x) => (x.id === replaceId ? { id: replaceId, role: 'assistant', status: 'loading' } : x)));
      } else {
        setMessages((m) => [
          ...m,
          { id: nextId(), role: 'user', text: q },
          { id: pendingId, role: 'assistant', status: 'loading' },
        ]);
        setDraft('');
      }
      try {
        const res = await ask.mutateAsync({ question: q, lang });
        setMessages((m) =>
          m.map((x) =>
            x.id === pendingId
              ? {
                  id: pendingId,
                  role: 'assistant',
                  status: 'done',
                  text: res.answer,
                  citations: res.citations ?? [],
                  // Rule: no citation or grounded=false -> fallback line, never a guess.
                  grounded: res.grounded === true && (res.citations?.length ?? 0) > 0,
                }
              : x,
          ),
        );
      } catch (err) {
        setMessages((m) =>
          m.map((x) =>
            x.id === pendingId
              ? { id: pendingId, role: 'assistant', status: 'error', errorKey: errorMessageKey(err), question: q }
              : x,
          ),
        );
      } finally {
        setBusy(false);
      }
    },
    [ask, busy, lang],
  );

  const retry = (question: string) => {
    const failed = messages.find((m) => m.role === 'assistant' && m.status === 'error' && m.question === question);
    if (failed) void send(question, failed.id);
  };

  return (
    <div className="flex flex-col">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h1>{t('ask.title')}</h1>
        <Link href={`/policy?id=${encodeURIComponent(id)}`} className="btn-ghost min-h-touch px-3">
          {t('ask.backToPolicy')}
        </Link>
      </div>

      {messages.length === 0 ? (
        <div className="card space-y-4 text-ink-soft">
          <p>{t('ask.intro')}</p>
          <div>
            <p className="font-medium text-ink">{t('ask.suggested')}</p>
            {suggestions.isLoading ? (
              <div className="mt-2 space-y-2" aria-hidden="true">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="h-12 animate-pulse rounded-card bg-surface-sunken" />
                ))}
              </div>
            ) : (
              <ul className="mt-2 space-y-2">
                {(suggestions.data ?? []).slice(0, 3).map((q) => (
                  <li key={q}>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void send(q)}
                      className="min-h-touch w-full rounded-card border border-brand-700 bg-surface px-4 py-2 text-left font-medium text-brand-800 hover:bg-brand-50 disabled:opacity-50"
                    >
                      {q}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      ) : (
        <ol role="log" aria-live="polite" aria-label={t('ask.title')} className="space-y-3">
          {messages.map((m) => (
            <ChatBubble key={m.id} msg={m} onRetry={retry} />
          ))}
          <li ref={endRef} aria-hidden="true" />
        </ol>
      )}

      <form
        className="sticky bottom-[calc(theme(spacing.tab-bar)+env(safe-area-inset-bottom))] z-10 -mx-4 mt-4 border-t border-surface-line bg-surface px-4 py-3"
        onSubmit={(e) => {
          e.preventDefault();
          void send(draft);
        }}
      >
        <label htmlFor="ask-input" className="sr-only">
          {t('ask.label')}
        </label>
        <div className="flex items-end gap-2">
          <textarea
            id="ask-input"
            rows={2}
            maxLength={MAX_LEN}
            value={draft}
            disabled={busy}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void send(draft);
              }
            }}
            placeholder={t('ask.placeholder')}
            className="input min-h-[3.5rem] resize-none py-3"
          />
          <VoiceInput
            lang={lang}
            disabled={busy}
            onStart={() => {
              baseRef.current = draft.trim();
            }}
            onTranscript={(text) => setDraft(`${baseRef.current}${baseRef.current && text ? ' ' : ''}${text}`.slice(0, MAX_LEN))}
            onStatus={setVoice}
          />
          <button type="submit" className="btn-primary min-h-touch-lg" disabled={busy || !draft.trim()}>
            {t('ask.send')}
          </button>
        </div>
        {(voice.listening || voice.errorKey) && (
          <p
            role={voice.errorKey ? 'alert' : 'status'}
            className={`mt-2 rounded-card border p-2 ${
              voice.errorKey ? 'border-danger-line bg-danger-bg text-danger-fg' : 'border-info-line bg-info-bg text-info-fg'
            }`}
          >
            {voice.errorKey ? t(voice.errorKey) : `🎤 ${t('voice.listening', { language: langName })}`}
          </p>
        )}
        <p className="mt-1 text-right text-ink-muted" aria-hidden="true">
          {draft.length}/{MAX_LEN}
        </p>
      </form>
    </div>
  );
}

function AskRoute() {
  const { t } = useTranslation();
  const id = useSearchParams().get('id');
  if (!id) {
    return (
      <EmptyState
        icon="policy"
        title={t('policy.noIdTitle')}
        body={t('policy.noIdBody')}
        action={{ label: t('processing.goHome'), href: '/' }}
      />
    );
  }
  return <AskChat id={id} />;
}

export default function PolicyAskPage() {
  return (
    <Suspense fallback={null}>
      <AskRoute />
    </Suspense>
  );
}
