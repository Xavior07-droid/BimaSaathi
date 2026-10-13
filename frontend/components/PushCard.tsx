'use client';
// F22: notification permission card for /renewals. Shows the right message for every state.
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import Icon from './Icon';
import { detectPush, enablePush, listenForeground, type ForegroundMessage, type PushState } from '@/lib/push';

interface Props {
  onStateChange?: (s: PushState) => void;
}

export default function PushCard({ onStateChange }: Props) {
  const { t } = useTranslation();
  const [state, setState] = useState<PushState>('checking');
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [live, setLive] = useState<ForegroundMessage | null>(null);

  const update = (s: PushState) => {
    setState(s);
    onStateChange?.(s);
  };

  useEffect(() => {
    let cancelled = false;
    void detectPush().then((s) => {
      if (!cancelled) update(s);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (state !== 'on') return;
    let off: (() => void) | undefined;
    let gone = false;
    void listenForeground(setLive).then((u) => {
      if (gone) u();
      else off = u;
    });
    return () => {
      gone = true;
      off?.();
    };
  }, [state]);

  const turnOn = async () => {
    setBusy(true);
    setFailed(false);
    const res = await enablePush();
    setBusy(false);
    if (res.ok) return update('on');
    if (res.reason === 'denied') return update('denied');
    if (res.reason === 'unsupported') return update('unsupported');
    setFailed(true);
  };

  if (state === 'checking') return null;

  return (
    <section className="card space-y-3" aria-labelledby="push-h">
      <h2 id="push-h" className="flex items-center gap-2">
        <Icon name="bell" className="h-6 w-6 text-brand-700" />
        {t('renewals.pushTitle')}
      </h2>

      {state === 'on' && (
        <p className="chip-success" role="status">
          <span aria-hidden="true">✓</span> {t('renewals.pushOn')}
        </p>
      )}

      {state === 'off' && (
        <>
          <p className="text-ink-soft">{t('renewals.pushOff')}</p>
          <button type="button" className="btn-primary w-full" onClick={() => void turnOn()} disabled={busy}>
            {busy ? t('renewals.pushing') : t('renewals.pushBtn')}
          </button>
        </>
      )}

      {state === 'denied' && (
        <p className="rounded-card border border-warning-line bg-warning-bg p-3 font-medium text-warning-fg">
          <span aria-hidden="true">⚠</span> {t('renewals.pushDenied')}
        </p>
      )}
      {state === 'unsupported' && (
        <p className="rounded-card border border-warning-line bg-warning-bg p-3 font-medium text-warning-fg">
          <span aria-hidden="true">⚠</span> {t('renewals.pushUnsupported')}
        </p>
      )}
      {state === 'unconfigured' && <p className="text-ink-soft">{t('renewals.pushUnconfigured')}</p>}

      {failed && (
        <p role="alert" className="rounded-card border border-danger-line bg-danger-bg p-3 font-medium text-danger-fg">
          ✕ {t('renewals.pushFailed')}
        </p>
      )}

      {live && (
        <div role="status" className="rounded-card border border-info-line bg-info-bg p-3 text-info-fg">
          <p className="font-semibold">{live.title}</p>
          {live.body && <p>{live.body}</p>}
        </div>
      )}

      <p className="text-ink-muted">{t('renewals.pushNote')}</p>
    </section>
  );
}
