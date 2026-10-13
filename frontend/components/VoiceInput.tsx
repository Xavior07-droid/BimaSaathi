'use client';
// F15: voice input with the Web Speech API (SpeechRecognition), locale en-IN / hi-IN / mr-IN.
// Free, in the browser. Not available everywhere (e.g. Firefox): then the mic button is hidden
// and the user simply types.
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import Icon from './Icon';
import { localeOf } from '@/lib/i18n';

// Minimal typings: TypeScript's DOM lib does not ship SpeechRecognition.
interface SRAlternative { transcript: string }
interface SRResult { isFinal: boolean; 0: SRAlternative }
interface SREvent { resultIndex: number; results: ArrayLike<SRResult> }
interface SRErrorEvent { error: string }
interface SR {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: SREvent) => void) | null;
  onerror: ((e: SRErrorEvent) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type SRCtor = new () => SR;

function getCtor(): SRCtor | null {
  if (typeof window === 'undefined') return null;
  const w = window as unknown as { SpeechRecognition?: SRCtor; webkitSpeechRecognition?: SRCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

function errorKey(code: string): string {
  switch (code) {
    case 'not-allowed':
    case 'service-not-allowed':
      return 'voice.errPermission';
    case 'no-speech':
      return 'voice.errNoSpeech';
    case 'language-not-supported':
      return 'voice.errLanguage';
    case 'network':
      return 'voice.errNetwork';
    case 'audio-capture':
      return 'voice.errMic';
    default:
      return 'voice.errGeneric';
  }
}

interface Props {
  lang: string; // 'en' | 'hi' | 'mr'
  disabled?: boolean;
  /** Called when listening starts (so the parent can remember what was already typed). */
  onStart: () => void;
  /** Live text while speaking (interim + final so far). */
  onTranscript: (text: string) => void;
  /** Lets the parent show a visible status line: listening, or an i18n error key. */
  onStatus: (s: { listening: boolean; errorKey: string | null }) => void;
}

export default function VoiceInput({ lang, disabled, onStart, onTranscript, onStatus }: Props) {
  const { t } = useTranslation();
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const rec = useRef<SR | null>(null);

  useEffect(() => {
    setSupported(getCtor() !== null); // after mount, so server and first client render match
    return () => rec.current?.abort();
  }, []);

  useEffect(() => {
    onStatus({ listening, errorKey: err });
  }, [listening, err, onStatus]);

  const stop = useCallback(() => rec.current?.stop(), []);

  // Language switched or input disabled (message sending): stop listening.
  useEffect(() => {
    if (disabled) rec.current?.abort();
  }, [disabled]);
  useEffect(() => () => rec.current?.abort(), [lang]);

  const start = () => {
    const Ctor = getCtor();
    if (!Ctor) return;
    setErr(null);
    const r = new Ctor();
    r.lang = localeOf(lang);
    r.continuous = false;
    r.interimResults = true;
    r.onresult = (e) => {
      let text = '';
      for (let i = 0; i < e.results.length; i++) text += e.results[i][0].transcript;
      onTranscript(text.trim());
    };
    r.onerror = (e) => {
      if (e.error !== 'aborted') setErr(errorKey(e.error));
    };
    r.onend = () => {
      setListening(false);
      if (rec.current === r) rec.current = null;
    };
    rec.current?.abort();
    rec.current = r;
    try {
      onStart();
      r.start();
      setListening(true);
    } catch {
      setListening(false);
      setErr('voice.errGeneric');
    }
  };

  if (!supported) return null;

  return (
    <button
      type="button"
      onClick={listening ? stop : start}
      disabled={disabled}
      aria-pressed={listening}
      aria-label={listening ? t('voice.stop') : t('voice.start')}
      className={`flex min-h-touch-lg min-w-touch-lg items-center justify-center rounded-card border font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
        listening
          ? 'border-danger-solid bg-danger-bg text-danger-fg'
          : 'border-brand-700 bg-surface text-brand-800 hover:bg-brand-50'
      }`}
    >
      <Icon name="mic" className={`h-7 w-7 ${listening ? 'animate-pulse motion-reduce:animate-none' : ''}`} />
    </button>
  );
}
