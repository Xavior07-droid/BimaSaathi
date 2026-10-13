'use client';
// Remembers the policy the user is working with, so tabs can link to /policy?id=... (static export:
// no dynamic routes). Stored in localStorage (wrapped in try/catch: it can be blocked or empty).
import { useEffect, useState } from 'react';

const KEY = 'bs_policy_id';
const EVENT = 'bs-policy-change';

export function getCurrentPolicyId(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function rememberPolicyId(id: string): void {
  try {
    window.localStorage.setItem(KEY, id);
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new Event(EVENT));
}

export function clearCurrentPolicyId(): void {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new Event(EVENT));
}

/** Current policy id (null until mounted, so server and first client render match). */
export function useCurrentPolicyId(): string | null {
  const [id, setId] = useState<string | null>(null);
  useEffect(() => {
    const sync = () => setId(getCurrentPolicyId());
    sync();
    window.addEventListener(EVENT, sync);
    window.addEventListener('storage', sync);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener('storage', sync);
    };
  }, []);
  return id;
}
