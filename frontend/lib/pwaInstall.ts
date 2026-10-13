'use client';
// F26: "Install app" support.
// - Chrome/Edge/Android fire `beforeinstallprompt`; we keep the event and show our own button.
// - iPhone/iPad Safari has no prompt, so we show "Share > Add to Home Screen" steps instead.
// The listener is registered as soon as this module loads (AppShell imports it) because the browser
// can fire the event long before the Settings screen opens.
import { useSyncExternalStore } from 'react';

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

let deferred: BeforeInstallPromptEvent | null = null;
let installed = false;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

if (typeof window !== 'undefined') {
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault(); // stop the browser's own mini-bar; we offer the button ourselves
    deferred = e as BeforeInstallPromptEvent;
    emit();
  });
  window.addEventListener('appinstalled', () => {
    deferred = null;
    installed = true;
    emit();
  });
}

export type InstallMode = 'installed' | 'prompt' | 'ios' | 'manual';

function isStandalone(): boolean {
  if (typeof window === 'undefined') return false;
  const nav = window.navigator as Navigator & { standalone?: boolean };
  return window.matchMedia?.('(display-mode: standalone)').matches || nav.standalone === true;
}

function isIos(): boolean {
  const ua = navigator.userAgent;
  // iPadOS 13+ reports itself as a Mac with a touch screen
  return /iPad|iPhone|iPod/.test(ua) || (ua.includes('Mac') && navigator.maxTouchPoints > 1);
}

function snapshot(): InstallMode {
  if (installed || isStandalone()) return 'installed';
  if (deferred) return 'prompt';
  return isIos() ? 'ios' : 'manual';
}

const subscribe = (cb: () => void) => {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
};

/** Current install situation. First render (server and hydration) is "manual" so markup matches. */
export function useInstallMode(): InstallMode {
  return useSyncExternalStore(subscribe, snapshot, () => 'manual' as InstallMode);
}

/** Shows the browser's install dialog. Returns true if the person accepted. */
export async function promptInstall(): Promise<boolean> {
  if (!deferred) return false;
  const ev = deferred;
  deferred = null; // an event can only be used once
  emit();
  try {
    await ev.prompt();
    const choice = await ev.userChoice;
    return choice.outcome === 'accepted';
  } catch {
    return false;
  }
}
