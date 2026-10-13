// Mock backend (F4) so UI work never waits for the API. Same interface as the real client.
// Enabled when NEXT_PUBLIC_USE_MOCKS=true. All data here is fake/synthetic.
import type { ApiClient } from './api';
import type {
  AskResponse, ClaimResult, CompareResponse, IngestStage, PolicyBrain, Reminder, ReviewClaim,
} from './types';

const delay = (ms = 400) => new Promise((r) => setTimeout(r, ms));

const POLICY_A: PolicyBrain = {
  policy_id: 'mock-policy-1',
  insurer: 'Sample Health Insurance Co.',
  policy_no: 'SHI/2026/000123',
  policy_type: 'health',
  holder_name: 'Sample Holder',
  start_date: '2026-01-15',
  end_date: '2027-01-14',
  renewal_date: '2027-01-15',
  sum_insured: 500000,
  premium: 14500,
  waiting_periods: { initial_days: 30, pre_existing_months: 36, specific_diseases_months: 24 },
  room_rent_cap: { value: 1, unit: 'percent_of_sum_insured' },
  copay_percent: 10,
  sub_limits: [
    { item: 'Cataract surgery (per eye)', limit: 40000, source: { page: 6, clause: '4.3' } },
    { item: 'Ambulance', limit: 2000, source: { page: 6, clause: '4.5' } },
  ],
  covered: [
    { text: 'Hospitalisation for 24 hours or more', source: { page: 3, clause: '2.1' } },
    { text: 'Pre-hospitalisation (30 days) and post-hospitalisation (60 days) costs', source: { page: 3, clause: '2.2' } },
    { text: 'Day-care procedures', source: { page: 4, clause: '2.4' } },
  ],
  exclusions: [
    { text: 'Cosmetic or plastic surgery', source: { page: 8, clause: '5.2' } },
    { text: 'Dental treatment unless caused by accident', source: { page: 8, clause: '5.6' } },
    { text: 'Treatment taken outside India', source: { page: 9, clause: '5.11' } },
  ],
  claim_requirements: {
    cashless: ['Health card', 'Photo ID', 'Pre-authorisation form'],
    reimbursement: ['Claim form', 'Discharge summary', 'Original bills', 'Payment receipts', 'Doctor prescription'],
    intimation_deadline_hours: 48,
  },
  red_flags: [
    { title: '10% co-pay on every claim', why_it_matters: 'You pay 10% of each hospital bill yourself. On a ₹1,00,000 bill that is ₹10,000.', source: { page: 5, clause: '3.4' } },
    { title: 'Room rent limited to 1% of sum insured', why_it_matters: 'A room costing more than ₹5,000 a day reduces the whole claim, not only the room part.', source: { page: 5, clause: '3.2' } },
  ],
  plain_summary: {
    en: 'This policy covers hospital stays up to ₹5,00,000 a year. You pay 10% of every bill and room rent is limited.',
    hi: 'यह पॉलिसी साल में ₹5,00,000 तक अस्पताल के खर्च को कवर करती है। हर बिल का 10% आपको देना होगा और कमरे का किराया सीमित है।',
    mr: 'ही पॉलिसी वर्षाला ₹5,00,000 पर्यंत रुग्णालयाचा खर्च कव्हर करते. प्रत्येक बिलाचे 10% तुम्हाला भरावे लागतील आणि खोलीचे भाडे मर्यादित आहे.',
  },
  extraction_meta: { model: 'mock', confidence: 0.9, file_hash: 'mockhash1', created_at: '2026-10-13T00:00:00Z' },
};

const POLICY_B: PolicyBrain = {
  ...POLICY_A,
  policy_id: 'mock-policy-2',
  insurer: 'Demo Mutual Insurance Ltd.',
  policy_no: 'DMI/2026/987654',
  start_date: '2026-03-01',
  end_date: '2027-02-28',
  renewal_date: '2027-03-01',
  sum_insured: 1000000,
  premium: 21800,
  copay_percent: 0,
  room_rent_cap: { value: 5000, unit: 'per_day' },
  waiting_periods: { initial_days: 30, pre_existing_months: 24, specific_diseases_months: 24 },
  extraction_meta: { ...POLICY_A.extraction_meta, file_hash: 'mockhash2' },
};

const POLICIES = [POLICY_A, POLICY_B];
const statusCalls: Record<string, number> = {};
const STAGES: IngestStage[] = ['uploading', 'reading', 'understanding', 'done'];

const findPolicy = (id: string) => POLICIES.find((p) => p.policy_id === id) ?? POLICY_A;

let reminders: Reminder[] = [
  { policy_id: 'mock-policy-1', policy_name: 'Sample Health Insurance Co.', renewal_date: '2027-01-15', premium: 14500, days_left: 94, status: 'upcoming', sent_flags: [] },
  { policy_id: 'mock-policy-2', policy_name: 'Demo Mutual Insurance Ltd.', renewal_date: '2026-10-20', premium: 21800, days_left: 7, status: 'due_soon', sent_flags: [30, 15] },
];

const REVIEW: ReviewClaim[] = [
  { claim_id: 'C-1007', hospital: 'City Care Hospital', procedure: 'Knee replacement', amount: 520000, risk_score: 88, action: null,
    flags: [{ rule: 'F1', severity: 'high', reason: 'Admitted 12 days after the policy started, which is inside the waiting period.' }, { rule: 'F3', severity: 'medium', reason: 'Amount is far above the usual cost for this procedure.' }] },
  { claim_id: 'C-1042', hospital: 'Lakeview Clinic', procedure: 'Appendectomy', amount: 98000, risk_score: 72, action: null,
    flags: [{ rule: 'F2', severity: 'high', reason: 'Same invoice number appears on another claim.' }] },
  { claim_id: 'C-1103', hospital: 'Sunrise Hospital', procedure: 'Cataract surgery', amount: 41000, risk_score: 35, action: null,
    flags: [{ rule: 'F5', severity: 'medium', reason: 'Many claims from this hospital in one week.' }] },
];

export const mockApi: ApiClient = {
  async health() { await delay(100); return { status: 'ok' }; },
  async ingestPolicy() { await delay(900); statusCalls['mock-policy-1'] = 0; return { policy_id: 'mock-policy-1', status: 'uploading', cached: false }; },
  async ingestSample() { await delay(300); statusCalls['mock-policy-1'] = 0; return { policy_id: 'mock-policy-1', status: 'uploading', cached: true }; },
  async getPolicyStatus(id) {
    await delay(300);
    if (id === 'mock-error') return { policy_id: id, status: 'error', error: { error_code: 'busy', message: 'busy' } };
    const n = (statusCalls[id] = (statusCalls[id] ?? 0) + 1);
    return { policy_id: id, status: STAGES[Math.min(n - 1, STAGES.length - 1)] ?? 'done' };
  },
  async getPolicy(id) { await delay(); return findPolicy(id); },
  async listPolicies() {
    await delay();
    return POLICIES.map((p) => ({ policy_id: p.policy_id, insurer: p.insurer, policy_type: p.policy_type, sum_insured: p.sum_insured, renewal_date: p.renewal_date }));
  },
  async getSuggestions(_id, lang) {
    await delay(200);
    return {
      en: ['Is cataract surgery covered?', 'What is my room rent limit?', 'How long is the waiting period?'],
      hi: ['क्या मोतियाबिंद का ऑपरेशन कवर है?', 'मेरे कमरे के किराये की सीमा क्या है?', 'वेटिंग पीरियड कितना है?'],
      mr: ['मोतीबिंदू शस्त्रक्रिया कव्हर आहे का?', 'माझ्या खोली भाड्याची मर्यादा किती?', 'प्रतीक्षा कालावधी किती आहे?'],
    }[lang];
  },
  async ask(_id, req) {
    await delay(900);
    const unclear = /xyz|bitcoin|lawsuit/i.test(req.question);
    const res: AskResponse = unclear
      ? { answer: 'The policy is not clear on this. Please confirm with your insurer.', citations: [], grounded: false, disclaimer: 'Not medical or legal advice.' }
      : { answer: 'Yes. Cataract surgery is covered up to ₹40,000 per eye.', citations: [{ page: 6, clause: '4.3' }], grounded: true, disclaimer: 'Not medical or legal advice.' };
    return res;
  },
  async checkClaim() {
    await delay(1500);
    const r: ClaimResult = {
      score: 72,
      rules: [
        { rule_id: 'R1', status: 'pass', reason: 'Admission is after the 30-day initial waiting period.', clause: { page: 4, clause: '3.1' } },
        { rule_id: 'R2', status: 'at_risk', reason: 'Tell the insurer within 48 hours of admission.', clause: { page: 7, clause: '6.2' } },
        { rule_id: 'R3', status: 'pass', reason: 'Diagnosis does not match any exclusion.', clause: { page: 8, clause: '5' } },
        { rule_id: 'R4', status: 'pass', reason: 'Estimated bill is within the sum insured.', clause: null },
        { rule_id: 'R5', status: 'pass', reason: 'Policy is active on the admission date.', clause: null },
      ],
      documents: [
        { doc_type: 'Claim form', status: 'found', issues: [] },
        { doc_type: 'Discharge summary', status: 'unclear', issues: ['Image is blurry', 'Doctor stamp not visible'] },
        { doc_type: 'Original bills', status: 'missing', issues: [] },
      ],
      top_actions: ['Upload the original hospital bills', 'Re-take the discharge summary photo in good light', 'Inform the insurer about the admission'],
      disclaimer: 'This is a readiness check, not a guarantee of claim approval.',
    };
    return r;
  },
  async compare(req) {
    await delay(1000);
    const ids = req.policy_ids;
    const rows = ids.map((id) => {
      const p = findPolicy(id);
      return { policy_id: p.policy_id, insurer: p.insurer, premium: p.premium, sum_insured: p.sum_insured, waiting_periods: p.waiting_periods, copay_percent: p.copay_percent, room_rent_cap: p.room_rent_cap, key_exclusions: p.exclusions.slice(0, 2).map((e) => e.text) };
    });
    const outcomes = ids.map((id, i) => ({
      policy_id: id,
      payable_by_insurer: i === 0 ? 72000 : 100000,
      copay_amount: i === 0 ? 7200 : 0,
      out_of_pocket: i === 0 ? 35200 : 0,
      how_calculated: ['Eligible room rent = min(rent, cap)', 'Payable = bill × eligible ÷ actual rent', 'Co-pay = payable × co-pay %', 'Out of pocket = bill − (payable − co-pay)'],
    }));
    const r: CompareResponse = { rows, outcomes, best_policy_id: ids[1] ?? ids[0] ?? null, recommendation: 'For this scenario the second policy leaves you with the lowest out-of-pocket cost because it has no co-pay.', label: 'simplified estimate' };
    return r;
  },
  async listReminders() { await delay(); return reminders; },
  async updateReminder(id, renewal_date) {
    await delay(300);
    reminders = reminders.map((r) => (r.policy_id === id ? { ...r, renewal_date } : r));
    return reminders.find((r) => r.policy_id === id) ?? reminders[0]!;
  },
  async testReminder() { await delay(500); return { sent: true }; },
  icsUrl(id) { return `data:text/calendar;charset=utf-8,${encodeURIComponent(`BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nSUMMARY:Renew ${id}\nEND:VEVENT\nEND:VCALENDAR`)}`; },
  async saveFcmToken() { await delay(200); return { ok: true }; },
  async saveConsent() { await delay(200); return { ok: true }; },
  async deleteMyData() { await delay(600); return { ok: true }; },
  async getReviewClaims() { await delay(); return { synthetic: true, claims: REVIEW }; },
  async reviewAction(id, action) { await delay(300); return { ...(REVIEW.find((c) => c.claim_id === id) ?? REVIEW[0]!), action }; },
};
