'use client';
// Web push (F22): permission -> service worker -> FCM token -> saved on the backend (M15).
// FCM web push is free on Firebase Spark. Everything is feature-detected: unsupported browsers,
// a missing VAPID key (demo mode) or a denied permission just show a clear message instead of failing.
import { api } from './api';
import { firebaseConfig, getFirebaseApp, isFirebaseConfigured } from './firebase';

export const VAPID_KEY = process.env.NEXT_PUBLIC_FIREBASE_VAPID_KEY ?? '';
const FLAG_KEY = 'bs_push_on';
const SW_URL = '/firebase-messaging-sw.js';
const SW_SCOPE = '/firebase-cloud-messaging-push-scope'; // the scope the Firebase SDK expects

export type PushState = 'checking' | 'unconfigured' | 'unsupported' | 'denied' | 'off' | 'on';
export type EnableResult = { ok: true } | { ok: false; reason: 'denied' | 'unsupported' | 'failed' };
export interface ForegroundMessage {
  title: string;
  body: string;
}

const readFlag = () => {
  try {
    return window.localStorage.getItem(FLAG_KEY) === '1';
  } catch {
    return false;
  }
};
const writeFlag = (on: boolean) => {
  try {
    if (on) window.localStorage.setItem(FLAG_KEY, '1');
    else window.localStorage.removeItem(FLAG_KEY);
  } catch {
    /* ignore */
  }
};

async function supported(): Promise<boolean> {
  if (typeof window === 'undefined' || !('Notification' in window) || !('serviceWorker' in navigator)) return false;
  const { isSupported } = await import('firebase/messaging');
  return isSupported();
}

/** Forget that notifications were switched on in this browser (used after "Delete my data"). */
export const clearPushFlag = () => writeFlag(false);

export async function detectPush(): Promise<PushState> {
  if (!isFirebaseConfigured || !VAPID_KEY) return 'unconfigured';
  if (!(await supported())) return 'unsupported';
  if (Notification.permission === 'denied') return 'denied';
  return Notification.permission === 'granted' && readFlag() ? 'on' : 'off';
}

function registerWorker(): Promise<ServiceWorkerRegistration> {
  const params = new URLSearchParams();
  (Object.entries(firebaseConfig) as [string, string | undefined][]).forEach(([k, v]) => {
    if (v) params.set(k, v);
  });
  return navigator.serviceWorker.register(`${SW_URL}?${params.toString()}`, { scope: SW_SCOPE });
}

/** Must be called from a tap (browsers only show the permission prompt after a user gesture). */
export async function enablePush(): Promise<EnableResult> {
  try {
    if (!(await supported())) return { ok: false, reason: 'unsupported' };
    const permission = await Notification.requestPermission();
    if (permission !== 'granted') {
      writeFlag(false);
      return { ok: false, reason: permission === 'denied' ? 'denied' : 'failed' };
    }
    const app = getFirebaseApp();
    if (!app) return { ok: false, reason: 'unsupported' };
    const registration = await registerWorker();
    await navigator.serviceWorker.ready;
    const { getMessaging, getToken } = await import('firebase/messaging');
    const token = await getToken(getMessaging(app), { vapidKey: VAPID_KEY, serviceWorkerRegistration: registration });
    if (!token) return { ok: false, reason: 'failed' };
    await api.saveFcmToken(token);
    writeFlag(true);
    return { ok: true };
  } catch {
    writeFlag(false);
    return { ok: false, reason: 'failed' };
  }
}

/** Messages that arrive while the app is open (the service worker only handles background ones). */
export async function listenForeground(cb: (m: ForegroundMessage) => void): Promise<() => void> {
  const app = getFirebaseApp();
  if (!app || !(await supported())) return () => {};
  const { getMessaging, onMessage } = await import('firebase/messaging');
  return onMessage(getMessaging(app), (payload) => {
    const d = payload.data ?? {};
    cb({
      title: payload.notification?.title ?? d.title ?? 'BimaSaathi',
      body: payload.notification?.body ?? d.body ?? '',
    });
  });
}
