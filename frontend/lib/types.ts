// Shared types, drafted from BUILD_PROMPT sections 4-5. Replace/adjust once M publishes docs/api.md.
// Rule: unknown values are null (the backend never guesses).

export type Lang = 'en' | 'hi' | 'mr';
export type IsoDate = string; // "YYYY-MM-DD"

export interface Source {
  page: number;
  clause: string;
}

export interface PolicyBrain {
  policy_id: string;
  insurer: string | null;
  policy_no: string | null;
  policy_type: 'health' | 'motor' | 'life' | null;
  holder_name: string | null;
  start_date: IsoDate | null;
  end_date: IsoDate | null;
  renewal_date: IsoDate | null;
  sum_insured: number | null; // INR integer
  premium: number | null; // INR integer
  waiting_periods: {
    initial_days: number | null;
    pre_existing_months: number | null;
    specific_diseases_months: number | null;
  };
  room_rent_cap: { value: number; unit: 'per_day' | 'percent_of_sum_insured' } | null;
  copay_percent: number | null;
  sub_limits: { item: string; limit: number | null; source: Source }[];
  covered: { text: string; source: Source }[];
  exclusions: { text: string; source: Source }[];
  claim_requirements: {
    cashless: string[];
    reimbursement: string[];
    intimation_deadline_hours: number | null;
  };
  red_flags: { title: string; why_it_matters: string; source: Source }[];
  plain_summary: Record<Lang, string>;
  extraction_meta: { model: string; confidence: number | null; file_hash: string; created_at: string };
}

/** Compact row for lists (GET /api/policies). */
export interface PolicySummary {
  policy_id: string;
  insurer: string | null;
  policy_type: PolicyBrain['policy_type'];
  sum_insured: number | null;
  renewal_date: IsoDate | null;
}

// ---- Ingest ----
export type IngestStage = 'uploading' | 'reading' | 'understanding' | 'done' | 'error';

export interface IngestResponse {
  policy_id: string;
  status: IngestStage;
  cached: boolean; // true if the same file was already processed
}

export interface PolicyStatus {
  policy_id: string;
  status: IngestStage;
  error?: ApiErrorBody;
}

// ---- Ask ----
export interface AskRequest {
  question: string;
  lang: Lang;
}
export interface AskResponse {
  answer: string;
  citations: Source[];
  grounded: boolean; // false -> show the "policy is not clear" fallback state
  disclaimer: string;
}

// ---- Claim check ----
export type ClaimType = 'cashless' | 'reimbursement';
export interface ClaimInput {
  policy_id: string;
  claim_type: ClaimType;
  admission_date: IsoDate;
  diagnosis: string;
  estimated_bill: number;
  documents: File[]; // up to 8 images, sent multipart, never stored
}
export type RuleStatus = 'pass' | 'fail' | 'at_risk';
export interface RuleResult {
  rule_id: 'R1' | 'R2' | 'R3' | 'R4' | 'R5';
  status: RuleStatus;
  reason: string;
  clause: Source | null;
}
export type DocStatus = 'found' | 'missing' | 'unclear';
export interface DocCheck {
  doc_type: string;
  status: DocStatus;
  issues: string[];
}
export interface ClaimResult {
  score: number; // 0-100, computed in code
  rules: RuleResult[];
  documents: DocCheck[];
  top_actions: string[]; // "do this first", max 3
  disclaimer: string; // "not a guarantee of claim approval"
}

// ---- Compare ----
export interface Scenario {
  days: number;
  room_rent_per_day: number;
  bill: number;
}
export interface CompareRow {
  policy_id: string;
  insurer: string | null;
  premium: number | null;
  sum_insured: number | null;
  waiting_periods: PolicyBrain['waiting_periods'];
  copay_percent: number | null;
  room_rent_cap: PolicyBrain['room_rent_cap'];
  key_exclusions: string[];
}
export interface CompareOutcome {
  policy_id: string;
  payable_by_insurer: number;
  copay_amount: number;
  out_of_pocket: number;
  how_calculated: string[]; // step-by-step lines, numbers come from code
}
export interface CompareResponse {
  rows: CompareRow[];
  outcomes: CompareOutcome[];
  best_policy_id: string | null;
  recommendation: string; // 3-4 lines from Gemini, no invented numbers
  label: 'simplified estimate';
}

// ---- Reminders / push ----
export type ReminderStatus = 'upcoming' | 'due_soon' | 'expired';
export interface Reminder {
  policy_id: string;
  policy_name: string;
  renewal_date: IsoDate | null;
  premium: number | null;
  days_left: number | null;
  status: ReminderStatus;
  sent_flags: number[]; // which of 30/15/7/1 were already sent
}

// ---- Review dashboard (synthetic) ----
export type RiskLevel = 'high' | 'medium' | 'low';
export interface FraudFlag {
  rule: 'F1' | 'F2' | 'F3' | 'F4' | 'F5';
  severity: RiskLevel;
  reason: string; // plain-language reword
}
export type ReviewAction = 'Escalate' | 'Clear' | 'Need more info';
export interface ReviewClaim {
  claim_id: string;
  hospital: string;
  procedure: string;
  amount: number;
  risk_score: number; // from rules only
  flags: FraudFlag[];
  action: ReviewAction | null;
}
export interface ReviewResponse {
  synthetic: true; // always true: UI must show the "Synthetic data" banner
  claims: ReviewClaim[];
}

// ---- Errors ----
export interface ApiErrorBody {
  error_code: string;
  message: string;
}
