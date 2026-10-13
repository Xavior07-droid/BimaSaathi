// F27: runs the REAL API client (lib/api.ts, mocks off) against the contract stub and checks that every
// call hits the right method/path with the right headers and body, and that errors are understood.
//   npm run test:contract
// This proves the frontend half of the contract. It does not prove M's backend: run it against the
// real server too with  CONTRACT_BASE=https://<render-url> npm run test:contract:live  (read-only checks).
import assert from 'node:assert/strict';
import type { AddressInfo } from 'node:net';
import { createContractServer } from './contract-server.mjs';

let pass = 0;
const results: string[] = [];
async function test(name: string, fn: () => Promise<void>) {
  try {
    await fn();
    pass++;
    results.push(`  ok   ${name}`);
  } catch (e) {
    results.push(`  FAIL ${name}\n       ${(e as Error).message}`);
    process.exitCode = 1;
  }
}

/** What a browser does before a cross-origin PATCH/DELETE/JSON/Authorization call: an OPTIONS preflight. */
async function corsCheck(base: string, origin: string) {
  for (const method of ['GET', 'POST', 'PATCH', 'DELETE']) {
    const res = await fetch(`${base}/api/policies`, {
      method: 'OPTIONS',
      headers: { Origin: origin, 'Access-Control-Request-Method': method, 'Access-Control-Request-Headers': 'authorization,content-type' },
    });
    assert.ok(res.status === 200 || res.status === 204, `${method} preflight from ${origin}: HTTP ${res.status}`);
    const acao = res.headers.get('access-control-allow-origin');
    assert.ok(acao === origin || acao === '*', `${method}: Access-Control-Allow-Origin is "${acao}", expected ${origin}`);
    const acam = (res.headers.get('access-control-allow-methods') ?? '').toUpperCase();
    assert.ok(acam.includes(method), `${method}: not in Access-Control-Allow-Methods ("${acam}")`);
    const acah = (res.headers.get('access-control-allow-headers') ?? '').toLowerCase();
    assert.ok(acah.includes('authorization') && acah.includes('content-type'), `${method}: Allow-Headers must include Authorization and Content-Type ("${acah}")`);
  }
}

async function main() {
  const live = process.env.CONTRACT_BASE;
  const stub = createContractServer({ requireAuth: true }); // like production: /api/* needs a Bearer token
  const listen = (s: ReturnType<typeof createContractServer>) =>
    new Promise<string>((r) => s.server.listen(0, () => r(`http://localhost:${(s.server.address() as AddressInfo).port}`)));
  const base = await listen(stub);

  process.env.NEXT_PUBLIC_USE_MOCKS = 'false';
  process.env.NEXT_PUBLIC_API_BASE = live ?? base;
  const { api, setAuthTokenGetter } = await import('../lib/api');
  const { ApiError, errorMessageKey } = await import('../lib/errors');
  const last = () => stub.log[stub.log.length - 1]!;

  if (live) {
    console.log(`LIVE mode against ${live}: read-only checks`);
    await test('GET /health answers (allow up to 90 s for a cold start)', async () => assert.equal((await api.health(90_000)).status, 'ok'));
    const origins = (process.env.CONTRACT_ORIGINS ?? 'http://localhost:3000,https://bimasaathi-a78d4.web.app,https://bimasaathi-a78d4.firebaseapp.com').split(',');
    for (const o of origins) await test(`CORS preflight allowed from ${o}`, () => corsCheck(live, o));
    console.log(results.join('\n'));
    process.exit(process.exitCode ?? 0);
  }

  setAuthTokenGetter(async () => 'tok123');

  await test('CORS preflight (GET/POST/PATCH/DELETE with Authorization) is answered for the app origin', () => corsCheck(base, 'http://localhost:3000'));
  await test('health sends NO Authorization header (simple CORS request)', async () => {
    await api.health();
    assert.equal(last().path, '/health');
    assert.equal(last().auth, null);
  });
  await test('api calls send Authorization: Bearer <token>', async () => {
    await api.listPolicies();
    assert.equal(last().auth, 'Bearer tok123');
  });
  await test('ingestPolicy: multipart field "file"', async () => {
    await api.ingestPolicy(new File(['x'], 'p.pdf', { type: 'application/pdf' }));
    assert.equal(last().method, 'POST');
    assert.equal(last().path, '/api/ingest');
    assert.deepEqual(last().parts, [{ name: 'file', filename: 'p.pdf' }]);
    assert.equal(last().ctype.startsWith('multipart/form-data; boundary='), true); // boundary set by fetch, not by us
  });
  await test('ingestSample / status / policy / policies / suggestions paths', async () => {
    await api.ingestSample();
    assert.equal(last().path, '/api/ingest/sample');
    assert.equal((await api.getPolicyStatus('p1')).status, 'done');
    assert.equal(last().path, '/api/policy/p1/status');
    assert.equal((await api.getPolicy('p1')).policy_id, 'p1');
    assert.equal(last().path, '/api/policy/p1');
    assert.equal((await api.listPolicies()).length, 2);
    assert.equal(last().path, '/api/policies');
    await api.getSuggestions('p1', 'hi');
    assert.equal(last().path, '/api/policy/p1/suggestions');
    assert.deepEqual(last().query, { lang: 'hi' });
  });
  await test('ask: POST JSON {question, lang}', async () => {
    const r = await api.ask('p1', { question: 'Is dengue covered?', lang: 'mr' });
    assert.equal(last().path, '/api/policy/p1/ask');
    assert.deepEqual(last().body, { question: 'Is dengue covered?', lang: 'mr' });
    assert.equal(r.grounded, true);
  });
  await test('checkClaim: multipart fields + max 8 documents', async () => {
    const docs = Array.from({ length: 10 }, (_, i) => new File(['x'], `d${i}.jpg`, { type: 'image/jpeg' }));
    await api.checkClaim({ policy_id: 'p1', claim_type: 'cashless', admission_date: '2026-10-01', diagnosis: 'Dengue', estimated_bill: 85000, documents: docs });
    assert.equal(last().path, '/api/claim/check');
    const names = (last().parts ?? []).map((p: { name: string }) => p.name);
    for (const f of ['policy_id', 'claim_type', 'admission_date', 'diagnosis', 'estimated_bill']) assert.ok(names.includes(f), `missing field ${f}`);
    assert.equal(names.filter((n: string) => n === 'documents').length, 8);
  });
  await test('compare: POST JSON {policy_ids, scenario}', async () => {
    const r = await api.compare({ policy_ids: ['p1', 'p2'], scenario: { days: 3, room_rent_per_day: 5000, bill: 100000 } });
    assert.equal(last().path, '/api/compare');
    assert.deepEqual(last().body, { policy_ids: ['p1', 'p2'], scenario: { days: 3, room_rent_per_day: 5000, bill: 100000 } });
    assert.equal(r.rows.length, 2);
    assert.equal(r.label, 'simplified estimate');
  });
  await test('reminders: GET / PATCH {renewal_date} / test {policy_id}', async () => {
    assert.equal((await api.listReminders()).length, 2);
    assert.equal(last().path, '/api/reminders');
    const u = await api.updateReminder('p2', '2027-05-05');
    assert.equal(last().method, 'PATCH');
    assert.equal(last().path, '/api/reminders/p2');
    assert.deepEqual(last().body, { renewal_date: '2027-05-05' });
    assert.equal(u.renewal_date, '2027-05-05');
    assert.equal((await api.testReminder('p1')).sent, true);
    assert.deepEqual(last().body, { policy_id: 'p1' });
  });
  await test('fcm-token / consent / fraud claims + action', async () => {
    await api.saveFcmToken('abc');
    assert.deepEqual(last().body, { token: 'abc' });
    await api.saveConsent();
    assert.equal(last().path, '/api/users/consent');
    const rc = await api.getReviewClaims();
    assert.equal(rc.synthetic, true);
    await api.reviewAction('C-1', 'Need more info');
    assert.equal(last().path, '/api/fraud/claims/C-1/action');
    assert.deepEqual(last().body, { action: 'Need more info' });
  });
  await test('deleteMyData: DELETE, tolerates 204 No Content', async () => {
    await api.deleteMyData();
    assert.equal(last().method, 'DELETE');
    assert.equal(last().path, '/api/me/data');
  });
  await test('ids are URL-encoded in paths', async () => {
    await api.getPolicy('a b/c').catch(() => {});
    assert.equal(last().path, '/api/policy/a%20b%2Fc');
  });

  // ---- error handling ----
  await test('FastAPI {detail:{error_code}} is unwrapped (404)', async () => {
    await assert.rejects(api.getPolicy('nope'), (e: unknown) => e instanceof ApiError && e.status === 404 && e.code === 'not_found');
  });
  await test('422 validation error keeps its error_code', async () => {
    await assert.rejects(api.compare({ policy_ids: ['p1'], scenario: { days: 1, room_rent_per_day: 1, bill: 1 } }), (e: unknown) => e instanceof ApiError && e.status === 422 && e.code === 'invalid_request');
  });
  await test('401 without a token -> ApiError 401 -> "signed out" message', async () => {
    setAuthTokenGetter(async () => null);
    await assert.rejects(api.listPolicies(), (e: unknown) => e instanceof ApiError && e.status === 401 && e.code === 'unauthorized' && errorMessageKey(e) === 'errors.signedOut');
    setAuthTokenGetter(async () => 'tok123');
  });
  await test('Render cold start: 503 + HTML body -> "busy" message, then recovers', async () => {
    stub.setCold(400);
    await assert.rejects(api.listPolicies(), (e: unknown) => e instanceof ApiError && e.status === 503 && errorMessageKey(e) === 'errors.busy');
    await assert.rejects(api.health(), (e: unknown) => e instanceof ApiError && e.status === 503); // health is retried by useServerStatus
    await new Promise((r) => setTimeout(r, 450));
    assert.equal((await api.health()).status, 'ok');
  });
  await test('non-JSON 200 body -> clear "bad_response" error, not a crash', async () => {
    const orig = globalThis.fetch;
    globalThis.fetch = (async () => new Response('<html>oops</html>', { status: 200 })) as typeof fetch;
    try {
      await assert.rejects(api.listPolicies(), (e: unknown) => e instanceof ApiError && e.code === 'bad_response' && errorMessageKey(e) === 'errors.generic');
    } finally {
      globalThis.fetch = orig;
    }
  });
  await test('server unreachable -> ApiError code "network"', async () => {
    stub.server.close();
    await assert.rejects(api.listPolicies(), (e: unknown) => e instanceof ApiError && e.code === 'network' && errorMessageKey(e) === 'errors.network');
  });

  console.log(results.join('\n'));
  console.log(`\n${pass}/${results.length} passed`);
  process.exit(process.exitCode ?? 0);
}

void main();
