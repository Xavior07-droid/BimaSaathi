// Stand-in for M's FastAPI backend (F27). Dependency-free Node server that speaks the SAME contract
// the frontend's real client (lib/api.ts) expects, including FastAPI-style error bodies and CORS.
// Purpose: run the real (non-mock) code path of the app end to end before the Render backend exists,
// and give M a runnable reference for the request/response shapes. It is NOT the real backend.
//
//   node scripts/contract-server.mjs            -> http://localhost:8099
//   REQUIRE_AUTH=1  : every /api call must carry "Authorization: Bearer ..." (else 401, like Firebase auth)
//   COLD_START_MS=N : answer 503 (HTML, like Render) for the first N ms, then work
import http from 'node:http';

const ALLOWED_ORIGINS = (process.env.ALLOWED_ORIGINS ?? 'http://localhost:3000').split(',');

const policy = (id, insurer, premium) => ({
  policy_id: id, insurer, policy_no: null, policy_type: 'health', holder_name: null,
  start_date: '2026-03-01', end_date: '2027-02-28', renewal_date: '2027-03-01', sum_insured: 1000000, premium,
  waiting_periods: { initial_days: 30, pre_existing_months: 24, specific_diseases_months: 24 },
  room_rent_cap: { value: 5000, unit: 'per_day' }, copay_percent: 10, sub_limits: [], covered: [], exclusions: [],
  claim_requirements: { cashless: ['Pre-authorisation form'], reimbursement: ['Original bills'], intimation_deadline_hours: 48 },
  red_flags: [], plain_summary: { en: 'Summary', hi: 'सारांश', mr: 'सारांश' },
  extraction_meta: { model: 'stub', confidence: 0.9, file_hash: id, created_at: '2026-10-13T00:00:00Z' },
});

export function createContractServer({ requireAuth = false, coldStartMs = 0 } = {}) {
  let coldUntil = Date.now() + coldStartMs; // 503 until then (like a sleeping Render service)
  const log = [];
  const policies = [policy('p1', 'Stub Insurer A', 14500), policy('p2', 'Stub Insurer B', 21800)];
  let reminders = policies.map((p, i) => ({
    policy_id: p.policy_id, policy_name: p.insurer, renewal_date: i ? '2026-10-20' : '2027-01-15', premium: p.premium,
    days_left: i ? 7 : 94, status: i ? 'due_soon' : 'upcoming', sent_flags: [],
  }));

  const server = http.createServer(async (req, res) => {
    const origin = req.headers.origin;
    const cors = {
      'Access-Control-Allow-Origin': ALLOWED_ORIGINS.includes(origin ?? '') ? origin : ALLOWED_ORIGINS[0],
      'Access-Control-Allow-Methods': 'GET,POST,PATCH,DELETE,OPTIONS',
      'Access-Control-Allow-Headers': 'Authorization,Content-Type',
      'Access-Control-Max-Age': '600',
      Vary: 'Origin',
    };
    const send = (status, body, extra = {}) => {
      const isHtml = typeof body === 'string';
      res.writeHead(status, { ...cors, 'Content-Type': isHtml ? 'text/html' : 'application/json', ...extra });
      res.end(status === 204 ? undefined : isHtml ? body : JSON.stringify(body));
    };
    const err = (status, error_code, message) => send(status, { detail: { error_code, message } }); // FastAPI wraps in "detail"

    if (req.method === 'OPTIONS') return send(204, '');
    const url = new URL(req.url ?? '/', 'http://x');
    const chunks = [];
    for await (const c of req) chunks.push(c);
    const raw = Buffer.concat(chunks);
    const ctype = req.headers['content-type'] ?? '';
    const entry = { method: req.method, path: url.pathname, query: Object.fromEntries(url.searchParams), auth: req.headers.authorization ?? null, ctype, body: null, parts: null };
    if (ctype.startsWith('application/json') && raw.length) entry.body = JSON.parse(raw.toString());
    if (ctype.startsWith('multipart/form-data')) {
      // Enough of a parser to list field names and file names (for contract assertions).
      const text = raw.toString('latin1');
      entry.parts = [...text.matchAll(/Content-Disposition: form-data; name="([^"]+)"(?:; filename="([^"]*)")?/g)].map((m) => ({ name: m[1], filename: m[2] ?? null }));
    }
    log.push(entry);

    if (Date.now() < coldUntil) return send(503, '<html><body>Service waking up</body></html>');
    if (url.pathname === '/health') return send(200, { status: 'ok' });
    if (url.pathname.startsWith('/api/') && requireAuth && !entry.auth) return err(401, 'unauthorized', 'Sign in required');

    const m = (re) => re.exec(url.pathname);
    let r;
    if (req.method === 'POST' && url.pathname === '/api/ingest') return send(200, { policy_id: 'p1', status: 'reading', cached: false });
    if (req.method === 'POST' && url.pathname === '/api/ingest/sample') return send(200, { policy_id: 'p1', status: 'done', cached: true });
    if (req.method === 'GET' && url.pathname === '/api/policies') return send(200, policies.map(({ policy_id, insurer, policy_type, sum_insured, renewal_date }) => ({ policy_id, insurer, policy_type, sum_insured, renewal_date })));
    if (req.method === 'GET' && (r = m(/^\/api\/policy\/([^/]+)\/status$/))) return send(200, { policy_id: r[1], status: 'done' });
    if (req.method === 'GET' && (r = m(/^\/api\/policy\/([^/]+)\/suggestions$/))) return send(200, ['What is not covered?', 'Is there a waiting period?']);
    if (req.method === 'POST' && (r = m(/^\/api\/policy\/([^/]+)\/ask$/))) {
      if (!entry.body?.question) return err(422, 'invalid_request', 'question is required');
      return send(200, { answer: 'Stub answer', citations: [{ page: 3, clause: '4.1' }], grounded: true, disclaimer: 'Stub' });
    }
    if (req.method === 'GET' && (r = m(/^\/api\/policy\/([^/]+)$/))) {
      const p = policies.find((x) => x.policy_id === r[1]);
      return p ? send(200, p) : err(404, 'not_found', 'Policy not found');
    }
    if (req.method === 'POST' && url.pathname === '/api/claim/check') {
      return send(200, { score: 72, rules: [{ rule_id: 'R1', status: 'pass', reason: 'ok', clause: { page: 5, clause: '3.1' } }], documents: [{ doc_type: 'Discharge summary', status: 'found', issues: [] }], top_actions: ['Add the original bills'], disclaimer: 'Not a guarantee' });
    }
    if (req.method === 'POST' && url.pathname === '/api/compare') {
      const ids = entry.body?.policy_ids ?? [];
      if (ids.length < 2) return err(422, 'invalid_request', 'Choose at least 2 policies');
      return send(200, {
        rows: ids.map((id) => { const p = policies.find((x) => x.policy_id === id) ?? policies[0]; return { policy_id: id, insurer: p.insurer, premium: p.premium, sum_insured: p.sum_insured, waiting_periods: p.waiting_periods, copay_percent: p.copay_percent, room_rent_cap: p.room_rent_cap, key_exclusions: [] }; }),
        outcomes: ids.map((id, i) => ({ policy_id: id, payable_by_insurer: 70000 + i * 10000, copay_amount: 7000, out_of_pocket: 37000 - i * 10000, how_calculated: ['Step 1', 'Step 2'] })),
        best_policy_id: ids[ids.length - 1], recommendation: 'Stub recommendation', label: 'simplified estimate',
      });
    }
    if (req.method === 'GET' && url.pathname === '/api/reminders') return send(200, reminders);
    if (req.method === 'PATCH' && (r = m(/^\/api\/reminders\/([^/]+)$/))) {
      reminders = reminders.map((x) => (x.policy_id === r[1] ? { ...x, renewal_date: entry.body?.renewal_date ?? x.renewal_date } : x));
      return send(200, reminders.find((x) => x.policy_id === r[1]) ?? reminders[0]);
    }
    if (req.method === 'POST' && url.pathname === '/api/reminders/test') return send(200, { sent: true });
    if (req.method === 'POST' && url.pathname === '/api/users/fcm-token') return entry.body?.token ? send(200, { ok: true }) : err(422, 'invalid_request', 'token required');
    if (req.method === 'POST' && url.pathname === '/api/users/consent') return send(200, { ok: true });
    if (req.method === 'DELETE' && url.pathname === '/api/me/data') return send(204, '');
    if (req.method === 'GET' && url.pathname === '/api/fraud/claims') return send(200, { synthetic: true, claims: [{ claim_id: 'C-1', hospital: 'H', procedure: 'P', amount: 1000, risk_score: 80, flags: [], action: null }] });
    if (req.method === 'POST' && (r = m(/^\/api\/fraud\/claims\/([^/]+)\/action$/))) return send(200, { claim_id: r[1], hospital: 'H', procedure: 'P', amount: 1000, risk_score: 80, flags: [], action: entry.body?.action ?? null });
    return err(404, 'not_found', `No route ${req.method} ${url.pathname}`);
  });
  return { server, log, setCold: (ms) => { coldUntil = Date.now() + ms; } };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const port = Number(process.env.PORT ?? 8099);
  const { server } = createContractServer({ requireAuth: process.env.REQUIRE_AUTH === '1', coldStartMs: Number(process.env.COLD_START_MS ?? 0) });
  server.listen(port, () => console.log(`Contract stub listening on http://localhost:${port}`));
}
