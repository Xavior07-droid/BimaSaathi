// Client-side upload validation. The backend validates again (never trust the client);
// this just gives instant, translated feedback. Limits come from the spec: PDF/JPG/PNG, max 15 MB.
export const MAX_UPLOAD_BYTES = 15 * 1024 * 1024;
export const ACCEPT_ATTR = '.pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png';

const OK_TYPES = ['application/pdf', 'image/jpeg', 'image/png'];
const OK_EXT = /\.(pdf|jpe?g|png)$/i;

/** Returns an i18n key for the problem, or null when the file is fine. */
export function validateUploadFile(file: File): string | null {
  // Some phones/browsers give an empty MIME type, so fall back to the extension.
  const typeOk = OK_TYPES.includes(file.type) || (file.type === '' && OK_EXT.test(file.name));
  if (!typeOk) return 'errors.fileType';
  if (file.size === 0) return 'errors.fileEmpty';
  if (file.size > MAX_UPLOAD_BYTES) return 'errors.fileSize';
  return null;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export const isImageFile = (f: File) => f.type.startsWith('image/') || /\.(jpe?g|png)$/i.test(f.name);

// ---- Claim documents (F18): photos only (JPG/PNG), as the claim checker reads images ----
export const CLAIM_DOC_ACCEPT = 'image/jpeg,image/png,.jpg,.jpeg,.png';

/** Returns an i18n key for the problem, or null when the photo is fine. */
export function validateClaimDoc(file: File): string | null {
  const typeOk = file.type === 'image/jpeg' || file.type === 'image/png' || (file.type === '' && /\.(jpe?g|png)$/i.test(file.name));
  if (!typeOk) return 'claim.errDocType';
  if (file.size === 0) return 'errors.fileEmpty';
  if (file.size > MAX_UPLOAD_BYTES) return 'errors.fileSize';
  return null;
}

// ---- Claim intake form (F17) ----
export const MAX_BILL_INR = 100_000_000; // Rs 10 crore, a sanity cap

export interface ClaimFormValues {
  claimType: 'cashless' | 'reimbursement' | '';
  admissionDate: string; // YYYY-MM-DD from <input type="date">
  diagnosis: string;
  bill: string; // digits only
}
export type ClaimFormErrors = Partial<Record<keyof ClaimFormValues, string>>; // values are i18n keys

const ISO = /^(\d{4})-(\d{2})-(\d{2})$/;
function isRealDate(s: string): boolean {
  const m = ISO.exec(s);
  if (!m) return false;
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
  return d.getUTCFullYear() === Number(m[1]) && d.getUTCMonth() === Number(m[2]) - 1 && d.getUTCDate() === Number(m[3]);
}

export function validateClaimForm(v: ClaimFormValues): ClaimFormErrors {
  const e: ClaimFormErrors = {};
  if (!v.claimType) e.claimType = 'claim.errType';
  if (!v.admissionDate) e.admissionDate = 'claim.errDateMissing';
  else if (!isRealDate(v.admissionDate)) e.admissionDate = 'claim.errDateInvalid';
  const dx = v.diagnosis.trim();
  if (dx.length < 2) e.diagnosis = 'claim.errDiagnosis';
  else if (dx.length > 200) e.diagnosis = 'claim.errDiagnosisLong';
  const bill = Number(v.bill);
  if (!v.bill) e.bill = 'claim.errBillMissing';
  else if (!Number.isInteger(bill) || bill <= 0) e.bill = 'claim.errBillInvalid';
  else if (bill > MAX_BILL_INR) e.bill = 'claim.errBillHigh';
  return e;
}

// ---- Compare scenario (F20) ----
export const MAX_SCENARIO_DAYS = 365;
export const MAX_ROOM_RENT_INR = 1_000_000;

export interface ScenarioValues {
  days: string; // digits only
  rent: string; // room rent per day, digits only
  bill: string; // total hospital bill, digits only
}
export type ScenarioErrors = Partial<Record<keyof ScenarioValues, string>>; // values are i18n keys

const wholeNumber = (v: string) => (v === '' ? NaN : Number(v));

export function validateScenario(v: ScenarioValues): ScenarioErrors {
  const e: ScenarioErrors = {};
  const days = wholeNumber(v.days);
  if (!v.days) e.days = 'compare.errDaysMissing';
  else if (!Number.isInteger(days) || days < 1 || days > MAX_SCENARIO_DAYS) e.days = 'compare.errDaysInvalid';
  const rent = wholeNumber(v.rent);
  if (!v.rent) e.rent = 'compare.errRentMissing';
  else if (!Number.isInteger(rent) || rent <= 0 || rent > MAX_ROOM_RENT_INR) e.rent = 'compare.errRentInvalid';
  const bill = wholeNumber(v.bill);
  if (!v.bill) e.bill = 'compare.errBillMissing';
  else if (!Number.isInteger(bill) || bill <= 0) e.bill = 'compare.errBillInvalid';
  else if (bill > MAX_BILL_INR) e.bill = 'compare.errBillHigh';
  return e;
}
