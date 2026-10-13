'use client';
// Auth + consent state. Google sign-in via Firebase Auth; the ID token is sent as
// "Authorization: Bearer <token>" on every API call (see setAuthTokenGetter in lib/api.ts).
// Without Firebase config the app offers a clearly labelled demo mode (sample data only).
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  GoogleAuthProvider, onAuthStateChanged, signInWithPopup, signInWithRedirect, signOut as fbSignOut,
} from 'firebase/auth';
import { api, setAuthTokenGetter } from './api';
import { clearCurrentPolicyId } from './currentPolicy';
import { getFirebaseAuth, isFirebaseConfigured } from './firebase';

export interface AppUser {
  uid: string;
  name: string | null;
  email: string | null;
  demo: boolean;
}

interface AuthState {
  user: AppUser | null;
  loading: boolean; // true until we know whether someone is signed in
  consented: boolean;
  error: string | null; // i18n key
  busy: boolean;
  signIn: () => Promise<void>;
  signInDemo: () => void;
  signOut: () => Promise<void>;
  acceptConsent: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

const DEMO_KEY = 'bs_demo_user';
const CONSENT_VERSION = 1; // bump when the consent text changes materially
const consentKey = (uid: string) => `bs_consent_v${CONSENT_VERSION}_${uid}`;

interface ConsentRecord {
  at: string;
  synced: boolean; // saved to the backend (consents/{uid})?
}

function readConsent(uid: string): ConsentRecord | null {
  try {
    const raw = window.localStorage.getItem(consentKey(uid));
    return raw ? (JSON.parse(raw) as ConsentRecord) : null;
  } catch {
    return null;
  }
}
function writeConsent(uid: string, rec: ConsentRecord): void {
  try {
    window.localStorage.setItem(consentKey(uid), JSON.stringify(rec));
  } catch {
    /* storage blocked: consent is kept in memory for this session only */
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<AppUser | null>(null);
  const [loading, setLoading] = useState(true);
  // Consent record + which user it was read for. Until it matches the current user we are still
  // "loading", otherwise a returning user would be bounced to /consent for one render.
  const [consentState, setConsentState] = useState<{ uid: string | null; rec: ConsentRecord | null }>({
    uid: null,
    rec: null,
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // 1) Send the Firebase ID token with every API call (the SDK refreshes it when it expires).
  useEffect(() => {
    setAuthTokenGetter(async () => {
      const u = getFirebaseAuth()?.currentUser;
      return u ? u.getIdToken() : null;
    });
  }, []);

  // 2) Track who is signed in.
  useEffect(() => {
    const auth = getFirebaseAuth();
    if (!auth) {
      try {
        const raw = window.localStorage.getItem(DEMO_KEY);
        if (raw) setUser(JSON.parse(raw) as AppUser);
      } catch {
        /* ignore */
      }
      setLoading(false);
      return;
    }
    return onAuthStateChanged(auth, (fb) => {
      setUser(fb ? { uid: fb.uid, name: fb.displayName, email: fb.email, demo: false } : null);
      setLoading(false);
    });
  }, []);

  // 3) Load this user's consent record.
  useEffect(() => {
    setConsentState({ uid: user?.uid ?? null, rec: user ? readConsent(user.uid) : null });
  }, [user]);

  const consentReady = user ? consentState.uid === user.uid : true;
  const consent = consentReady ? consentState.rec : null;

  // 4) If consent was given while the backend was unreachable, save it now (best effort).
  useEffect(() => {
    if (!user || !consent || consent.synced) return;
    let cancelled = false;
    api
      .saveConsent()
      .then(() => {
        const rec = { ...consent, synced: true };
        writeConsent(user.uid, rec);
        if (!cancelled) setConsentState({ uid: user.uid, rec });
      })
      .catch(() => {
        /* try again next time the app opens */
      });
    return () => {
      cancelled = true;
    };
  }, [user, consent]);

  const signIn = useCallback(async () => {
    const auth = getFirebaseAuth();
    if (!auth) return;
    setError(null);
    setBusy(true);
    const provider = new GoogleAuthProvider();
    try {
      await signInWithPopup(auth, provider);
    } catch (e) {
      const code = (e as { code?: string }).code ?? '';
      if (code === 'auth/popup-blocked' || code === 'auth/operation-not-supported-in-this-environment') {
        await signInWithRedirect(auth, provider); // some mobile browsers block popups
        return;
      }
      if (code !== 'auth/popup-closed-by-user' && code !== 'auth/cancelled-popup-request') {
        setError(code === 'auth/network-request-failed' ? 'errors.network' : 'auth.failed');
      }
    } finally {
      setBusy(false);
    }
  }, []);

  const signInDemo = useCallback(() => {
    const demo: AppUser = { uid: 'demo-user', name: 'Demo user', email: null, demo: true };
    try {
      window.localStorage.setItem(DEMO_KEY, JSON.stringify(demo));
    } catch {
      /* ignore */
    }
    setUser(demo);
  }, []);

  const signOut = useCallback(async () => {
    const auth = getFirebaseAuth();
    if (auth) await fbSignOut(auth);
    try {
      window.localStorage.removeItem(DEMO_KEY);
    } catch {
      /* ignore */
    }
    queryClient.clear(); // drop cached policies of the previous user
    clearCurrentPolicyId();
    setUser(null);
  }, [queryClient]);

  const acceptConsent = useCallback(async () => {
    if (!user) return;
    setBusy(true);
    const rec: ConsentRecord = { at: new Date().toISOString(), synced: false };
    try {
      await api.saveConsent();
      rec.synced = true;
    } catch {
      /* saved locally, synced on next load (effect above) */
    }
    writeConsent(user.uid, rec);
    setConsentState({ uid: user.uid, rec });
    setBusy(false);
  }, [user]);

  const value = useMemo<AuthState>(
    () => ({ user, loading: loading || !consentReady, consented: !!consent, error, busy, signIn, signInDemo, signOut, acceptConsent }),
    [user, loading, consentReady, consent, error, busy, signIn, signInDemo, signOut, acceptConsent],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}

export { isFirebaseConfigured };
