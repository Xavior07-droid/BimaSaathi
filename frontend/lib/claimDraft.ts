'use client';
// Keeps the claim details between the form (F17), document grid (F18) and result (F19).
// sessionStorage = cleared when the tab closes; wrapped in try/catch (can be blocked or empty).
import type { ClaimFormValues } from './validate';

const KEY = 'bs_claim_draft';

export function loadClaimDraft(): ClaimFormValues | null {
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (!raw) return null;
    const v = JSON.parse(raw) as Partial<ClaimFormValues>;
    return {
      claimType: v.claimType === 'cashless' || v.claimType === 'reimbursement' ? v.claimType : '',
      admissionDate: typeof v.admissionDate === 'string' ? v.admissionDate : '',
      diagnosis: typeof v.diagnosis === 'string' ? v.diagnosis : '',
      bill: typeof v.bill === 'string' ? v.bill.replace(/\D/g, '') : '',
    };
  } catch {
    return null;
  }
}

export function saveClaimDraft(v: ClaimFormValues): void {
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify(v));
  } catch {
    /* ignore: user just re-enters details */
  }
}

export function clearClaimDraft(): void {
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
