// Typed API client (F4). Real client + mock layer share one interface (ApiClient).
// Endpoints follow BUILD_PROMPT section 5. Items marked (assumed) are not in the prompt;
// confirm against M's docs/api.md (M5) and adjust here only.
import { ApiError } from './errors';
import type {
  ApiErrorBody, AskRequest, AskResponse, ClaimInput, ClaimResult, CompareResponse, IngestResponse,
  Lang, PolicyBrain, PolicyStatus, PolicySummary, Reminder, ReviewAction, ReviewClaim, ReviewResponse,
  Scenario,
} from './types';

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? 'http://localhost:8000').replace(/\/$/, '');
export const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS === 'true';

export interface ApiClient {
  health(timeoutMs?: number): Promise<{ status: string }>;
  ingestPolicy(file: File): Promise<IngestResponse>;
  ingestSample(): Promise<IngestResponse>; // (assumed) "try sample policy": backend returns sample_policy.json
  getPolicyStatus(id: string): Promise<PolicyStatus>;
  getPolicy(id: string): Promise<PolicyBrain>;
  listPolicies(): Promise<PolicySummary[]>;
  getSuggestions(id: string, lang: Lang): Promise<string[]>;
  ask(id: string, req: AskRequest): Promise<AskResponse>;
  checkClaim(input: ClaimInput): Promise<ClaimResult>;
  compare(req: { policy_ids: string[]; scenario: Scenario }): Promise<CompareResponse>;
  listReminders(): Promise<Reminder[]>; // (assumed) GET /api/reminders
  updateReminder(policyId: string, renewalDate: string): Promise<Reminder>; // (assumed) PATCH /api/reminders/{id}
  testReminder(policyId: string): Promise<{ sent: boolean }>;
  icsUrl(policyId: string): string;
  saveFcmToken(token: string): Promise<{ ok: boolean }>;
  saveConsent(): Promise<{ ok: boolean }>; // (assumed) POST /api/users/consent
  deleteMyData(): Promise<{ ok: boolean }>;
  getReviewClaims(): Promise<ReviewResponse>;
  reviewAction(claimId: string, action: ReviewAction): Promise<ReviewClaim>;
}

// ---- Auth: F7 plugs in Firebase here. Until then requests go without a token. ----
type TokenGetter = () => Promise<string | null>;
let getToken: TokenGetter = async () => null;
export function setAuthTokenGetter(fn: TokenGetter): void {
  getToken = fn;
}

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = 30000, auth = true): Promise<T> {
  const headers = new Headers(init.headers);
  // /health is public: no token, so the warm-up ping stays a simple CORS request (no preflight).
  const token = auth ? await getToken() : null;
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers, signal: ctrl.signal });
  } catch {
    // Offline, CORS failure, DNS, or the free server is still waking up.
    throw new ApiError(0, { error_code: 'network', message: 'Network error' });
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    let body: ApiErrorBody = { error_code: 'unknown', message: res.statusText };
    try {
      const j = await res.json();
      const d = j?.detail ?? j; // FastAPI wraps errors in "detail"
      if (d && typeof d === 'object' && 'error_code' in d) body = d as ApiErrorBody;
    } catch { /* non-JSON error body */ }
    throw new ApiError(res.status, body);
  }
  // Tolerate empty bodies (204 No Content) and report a non-JSON success body as a clear error.
  const text = await res.text();
  if (!text) return {} as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(502, { error_code: 'bad_response', message: 'Unexpected server response' });
  }
}

const post = <T,>(path: string, body: unknown, ms?: number) =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body) }, ms);

const realApi: ApiClient = {
  health: (timeoutMs = 60000) => request('/health', {}, timeoutMs, false), // slow on Render free-tier cold start
  ingestPolicy(file) {
    const fd = new FormData();
    fd.append('file', file);
    return request('/api/ingest', { method: 'POST', body: fd }, 120000);
  },
  ingestSample: () => post('/api/ingest/sample', {}),
  getPolicyStatus: (id) => request(`/api/policy/${encodeURIComponent(id)}/status`),
  getPolicy: (id) => request(`/api/policy/${encodeURIComponent(id)}`),
  listPolicies: () => request('/api/policies'),
  getSuggestions: (id, lang) => request(`/api/policy/${encodeURIComponent(id)}/suggestions?lang=${lang}`),
  ask: (id, req) => post(`/api/policy/${encodeURIComponent(id)}/ask`, req, 60000),
  checkClaim(input) {
    const fd = new FormData();
    fd.append('policy_id', input.policy_id);
    fd.append('claim_type', input.claim_type);
    fd.append('admission_date', input.admission_date);
    fd.append('diagnosis', input.diagnosis);
    fd.append('estimated_bill', String(input.estimated_bill));
    input.documents.slice(0, 8).forEach((f) => fd.append('documents', f));
    return request<ClaimResult>('/api/claim/check', { method: 'POST', body: fd }, 90000);
  },
  compare: (req) => post<CompareResponse>('/api/compare', req, 60000),
  listReminders: () => request('/api/reminders'),
  updateReminder: (id, renewal_date) =>
    request(`/api/reminders/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ renewal_date }) }),
  testReminder: (id) => post('/api/reminders/test', { policy_id: id }),
  icsUrl: (id) => `${API_BASE}/api/reminders/${encodeURIComponent(id)}/ics`,
  saveFcmToken: (token) => post('/api/users/fcm-token', { token }),
  saveConsent: () => post('/api/users/consent', { accepted: true }),
  deleteMyData: () => request('/api/me/data', { method: 'DELETE' }),
  getReviewClaims: () => request('/api/fraud/claims'),
  reviewAction: (id, action) => post(`/api/fraud/claims/${encodeURIComponent(id)}/action`, { action }),
};

// Mock data is loaded on demand, so a real (USE_MOCKS=false) build never downloads the sample fixtures.
const lazyMockApi = new Proxy({} as ApiClient, {
  get:
    (_t, key: string) =>
    (...args: unknown[]) =>
      import('./mocks').then((m) => (m.mockApi as unknown as Record<string, (...a: unknown[]) => unknown>)[key]!(...args)),
});

/** The one client the app uses. Switch with NEXT_PUBLIC_USE_MOCKS. */
export const api: ApiClient = USE_MOCKS ? lazyMockApi : realApi;
