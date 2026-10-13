'use client';
// F13: "Listen" player. Reads the text aloud with the browser voice for the chosen language.
// No voice installed -> show the text + a short notice (never a wrong-language voice).
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { LANGUAGES } from '@/lib/i18n';
import {
  findVoice, pauseSpeaking, resumeSpeaking, speak, speechSupported, stopSpeaking,
} from '@/lib/speech';

type State = 'idle' | 'loading' | 'playing' | 'paused' | 'novoice' | 'error';

function PlayIcon({ kind }: { kind: 'play' | 'pause' | 'stop' }) {
  const d = kind === 'play' ? 'M8 5v14l11-7z' : kind === 'pause' ? 'M7 5h4v14H7zM13 5h4v14h-4z' : 'M6 6h12v12H6z';
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className="h-6 w-6">
      <path d={d} />
    </svg>
  );
}

export default function AudioPlayer({ text, lang }: { text: string; lang: string }) {
  const { t } = useTranslation();
  const [state, setState] = useState<State>('idle');
  const [supported, setSupported] = useState(true);
  const alive = useRef(true);
  const langLabel = LANGUAGES.find((l) => l.code === lang)?.label ?? lang;

  useEffect(() => {
    alive.current = true;
    setSupported(speechSupported()); // after mount, so server and first client render match
    return () => {
      alive.current = false;
      stopSpeaking();
    };
  }, []);

  // Language or text changed (user switched EN/HI/MR): stop old audio, reset.
  useEffect(() => {
    stopSpeaking();
    setState('idle');
  }, [lang, text]);

  const play = useCallback(async () => {
    setState('loading');
    const voice = await findVoice(lang);
    if (!alive.current) return;
    if (!voice) return setState('novoice');
    setState('playing');
    speak(text, lang, voice, {
      onEnd: () => alive.current && setState('idle'),
      onError: () => alive.current && setState('error'),
    });
  }, [lang, text]);

  const pause = () => {
    pauseSpeaking();
    setState('paused');
  };
  const resume = () => {
    resumeSpeaking();
    setState('playing');
  };
  const stop = () => {
    stopSpeaking();
    setState('idle');
  };

  if (!supported) {
    return (
      <p role="status" className="rounded-card border border-info-line bg-info-bg p-3 text-info-fg">
        {t('audio.unsupported')}
      </p>
    );
  }

  const active = state === 'playing' || state === 'paused';

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {state === 'playing' ? (
          <button type="button" className="btn-primary" onClick={pause}>
            <PlayIcon kind="pause" /> {t('audio.pause')}
          </button>
        ) : state === 'paused' ? (
          <button type="button" className="btn-primary" onClick={resume}>
            <PlayIcon kind="play" /> {t('audio.resume')}
          </button>
        ) : (
          <button type="button" className="btn-primary" onClick={play} disabled={state === 'loading'}>
            <PlayIcon kind="play" /> {state === 'loading' ? t('common.loading') : t('audio.play', { language: langLabel })}
          </button>
        )}
        {active && (
          <button type="button" className="btn-secondary" onClick={stop}>
            <PlayIcon kind="stop" /> {t('audio.stop')}
          </button>
        )}
      </div>

      <p role="status" aria-live="polite" className="sr-only">
        {state === 'playing' ? t('audio.playing') : state === 'paused' ? t('audio.paused') : ''}
      </p>

      {state === 'novoice' && (
        <div role="status" className="space-y-2 rounded-card border border-warning-line bg-warning-bg p-3 text-warning-fg">
          <p className="font-semibold">{t('audio.noVoice', { language: langLabel })}</p>
          <p lang={lang} className="text-ink">
            {text}
          </p>
        </div>
      )}
      {state === 'error' && (
        <p role="alert" className="rounded-card border border-danger-line bg-danger-bg p-3 text-danger-fg">
          {t('audio.error')}
        </p>
      )}
    </div>
  );
}
