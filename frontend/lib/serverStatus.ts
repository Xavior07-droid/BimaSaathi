'use client';
// Cold-start handling for the free Render backend (it sleeps when idle and needs up to ~1 minute to wake).
// The app pings /health on load: this also warms the server up before the user needs it.
import { useCallback, useEffect, useState } from 'react';
import { api } from './api';

export type ServerState = 'checking' | 'waking' | 'ready' | 'failed';

const num = (v: string | undefined, d: number) => (v && !Number.isNaN(Number(v)) ? Number(v) : d);
/** Show the "waking up" message only if the server has not answered after this long. */
export const SHOW_AFTER_MS = num(process.env.NEXT_PUBLIC_WAKE_SHOW_AFTER_MS, 2500);
/** Give up after this long (Render cold start is usually 30-60 s). */
export const DEADLINE_MS = num(process.env.NEXT_PUBLIC_WAKE_DEADLINE_MS, 90000);
const ATTEMPT_MS = 15000; // timeout for one ping
const RETRY_MS = 2000; // pause between pings

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function useServerStatus(): { state: ServerState; elapsed: number; retry: () => void } {
  const [state, setState] = useState<ServerState>('checking');
  const [elapsed, setElapsed] = useState(0);
  const [run, setRun] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const start = Date.now();
    setState('checking');
    setElapsed(0);

    const slow = setTimeout(() => {
      if (!cancelled) setState((s) => (s === 'checking' ? 'waking' : s));
    }, SHOW_AFTER_MS);
    const tick = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    const stop = () => {
      clearTimeout(slow);
      clearInterval(tick);
    };

    (async () => {
      while (!cancelled && Date.now() - start < DEADLINE_MS) {
        try {
          await api.health(ATTEMPT_MS);
          if (!cancelled) setState('ready');
          stop();
          return;
        } catch {
          await sleep(RETRY_MS); // 503/timeout while the server boots: keep trying
        }
      }
      if (!cancelled) setState('failed');
      stop();
    })();

    return () => {
      cancelled = true;
      stop();
    };
  }, [run]);

  const retry = useCallback(() => setRun((n) => n + 1), []);
  return { state, elapsed, retry };
}
