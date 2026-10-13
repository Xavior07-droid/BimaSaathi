// F13: browser text-to-speech (speechSynthesis). Free, no backend, works offline once voices exist.
// If the device has no voice for the language we do NOT speak with a wrong voice:
// the UI shows the text and a short notice instead (spec section 2).
import { localeOf } from './i18n';

export const speechSupported = (): boolean =>
  typeof window !== 'undefined' && 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window;

/** Voices load asynchronously on most browsers; wait briefly for them. */
function loadVoices(timeoutMs = 1500): Promise<SpeechSynthesisVoice[]> {
  return new Promise((resolve) => {
    const synth = window.speechSynthesis;
    const now = synth.getVoices();
    if (now.length > 0) return resolve(now);
    const done = () => {
      synth.removeEventListener('voiceschanged', done);
      clearTimeout(timer);
      resolve(synth.getVoices());
    };
    const timer = setTimeout(done, timeoutMs);
    synth.addEventListener('voiceschanged', done);
  });
}

/** Best installed voice for en-IN / hi-IN / mr-IN, or null when none exists. */
export async function findVoice(lang: string): Promise<SpeechSynthesisVoice | null> {
  if (!speechSupported()) return null;
  const locale = localeOf(lang).toLowerCase();
  const base = locale.split('-')[0];
  const voices = await loadVoices();
  const norm = (v: SpeechSynthesisVoice) => v.lang.toLowerCase().replace('_', '-');
  return (
    voices.find((v) => norm(v) === locale) ??
    voices.find((v) => norm(v).startsWith(`${base}-`) || norm(v) === base) ??
    null
  );
}

/** Split into short chunks: long utterances get cut off by Chrome after ~15 seconds. */
export function chunkText(text: string, max = 180): string[] {
  const sentences = text.replace(/\s+/g, ' ').trim().match(/[^.!?।]+[.!?।]*\s*/g) ?? [];
  const out: string[] = [];
  let cur = '';
  const push = () => {
    if (cur.trim()) out.push(cur.trim());
    cur = '';
  };
  for (const s of sentences) {
    if (s.length > max) {
      push();
      const words = s.split(' ');
      for (const w of words) {
        if ((cur + ' ' + w).length > max) push();
        cur += (cur ? ' ' : '') + w;
      }
      push();
    } else if ((cur + s).length > max) {
      push();
      cur = s;
    } else {
      cur += s;
    }
  }
  push();
  return out;
}

export interface SpeakHandlers {
  onEnd: () => void;
  onError: () => void;
}

/** Speak text with the given voice. Call stopSpeaking() to cancel. */
export function speak(text: string, lang: string, voice: SpeechSynthesisVoice, h: SpeakHandlers): void {
  const synth = window.speechSynthesis;
  synth.cancel();
  const chunks = chunkText(text);
  if (chunks.length === 0) return h.onEnd();
  chunks.forEach((c, i) => {
    const u = new SpeechSynthesisUtterance(c);
    u.voice = voice;
    u.lang = voice.lang || localeOf(lang);
    u.rate = 0.9; // a little slower is easier to follow
    if (i === chunks.length - 1) u.onend = () => h.onEnd();
    u.onerror = (e) => {
      // "canceled"/"interrupted" happen when we stop on purpose: not an error.
      if (e.error === 'canceled' || e.error === 'interrupted') return;
      h.onError();
    };
    synth.speak(u);
  });
}

export const pauseSpeaking = () => speechSupported() && window.speechSynthesis.pause();
export const resumeSpeaking = () => speechSupported() && window.speechSynthesis.resume();
export const stopSpeaking = () => speechSupported() && window.speechSynthesis.cancel();
