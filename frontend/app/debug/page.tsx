'use client';
// F27: developer connection check. Not linked anywhere and OFF unless NEXT_PUBLIC_DEBUG=true.
// Shows whether the app is on mocks or the real API, and pings the read-only endpoints with timings,
// so cold-start, CORS and auth problems on a real phone are visible in seconds. English only on purpose.
import { useState } from 'react';
import { api, API_BASE, USE_MOCKS } from '@/lib/api';
import { ApiError } from '@/lib/errors';
import { isFirebaseConfigured, useAuth } from '@/lib/auth';
import { VAPID_KEY } from '@/lib/push';
import { useOnline } from '@/lib/useOnline';

const ENABLED = process.env.NEXT_PUBLIC_DEBUG === 'true';

interface Row {
  name: string;
  ok: boolean;
  ms: number;
  detail: string;
}

const CHECKS: { name: string; run: () => Promise<unknown> }[] = [
  { name: 'GET /health', run: () => api.health(90_000) },
  { name: 'GET /api/policies', run: () => api.listPolicies() },
  { name: 'GET /api/reminders', run: () => api.listReminders() },
  { name: 'GET /api/fraud/claims', run: () => api.getReviewClaims() },
];

export default function DebugPage() {
  const { user } = useAuth();
  const online = useOnline();
  const [rows, setRows] = useState<Row[]>([]);
  const [busy, setBusy] = useState(false);

  if (!ENABLED) {
    return <p className="card text-ink-soft">Debug page is off. Build with NEXT_PUBLIC_DEBUG=true to turn it on.</p>;
  }

  const run = async () => {
    setBusy(true);
    setRows([]);
    for (const c of CHECKS) {
      const t0 = performance.now();
      let row: Row;
      try {
        const r = await c.run();
        const n = Array.isArray(r) ? `${r.length} items` : 'ok';
        row = { name: c.name, ok: true, ms: Math.round(performance.now() - t0), detail: n };
      } catch (e) {
        const detail = e instanceof ApiError ? `HTTP ${e.status} ${e.code}` : String(e);
        row = { name: c.name, ok: false, ms: Math.round(performance.now() - t0), detail };
      }
      setRows((r) => [...r, row]);
    }
    setBusy(false);
  };

  const info: [string, string][] = [
    ['Mode', USE_MOCKS ? 'MOCKS (sample data)' : 'REAL API'],
    ['API base', API_BASE],
    ['Online', online ? 'yes' : 'no'],
    ['Firebase configured', isFirebaseConfigured ? 'yes' : 'no'],
    ['VAPID key present', VAPID_KEY ? 'yes' : 'no'],
    ['Signed in', user ? `${user.demo ? 'demo' : 'Google'} (${user.uid.slice(0, 8)}…)` : 'no'],
    ['Page origin', typeof window !== 'undefined' ? window.location.origin : ''],
  ];

  return (
    <div className="space-y-4">
      <h1>Connection check</h1>
      <dl className="card space-y-2 font-mono text-sm">
        {info.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-3">
            <dt className="text-ink-muted">{k}</dt>
            <dd className="break-all text-right font-semibold">{v}</dd>
          </div>
        ))}
      </dl>
      {USE_MOCKS && <p className="chip-warning">Mocks are ON: these checks only test the sample-data layer.</p>}
      <button type="button" className="btn-primary w-full" onClick={() => void run()} disabled={busy}>
        {busy ? 'Checking… (a cold start can take up to a minute)' : 'Run checks'}
      </button>
      {rows.length > 0 && (
        <ul className="space-y-2 font-mono text-sm" data-testid="debug-results">
          {rows.map((r) => (
            <li key={r.name} className={r.ok ? 'chip-success w-full justify-between' : 'chip-danger w-full justify-between'}>
              <span>
                <span aria-hidden="true">{r.ok ? '✓' : '✕'}</span> {r.name}
              </span>
              <span>
                {r.detail} · {r.ms} ms
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
