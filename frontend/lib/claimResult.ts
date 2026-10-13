'use client';
// Hands the claim-check result from /claim to /claim/result (F19). sessionStorage only: the result
// is cleared when the tab closes, and nothing about the uploaded photos is kept (only the score data).
import type { ClaimResult } from './types';

const KEY = 'bs_claim_result';

export interface StoredClaimResult {
  policyId: string;
  result: ClaimResult;
  checkedAt: string; // ISO timestamp
}

export function saveClaimResult(policyId: string, result: ClaimResult): void {
  try {
    const v: StoredClaimResult = { policyId, result, checkedAt: new Date().toISOString() };
    window.sessionStorage.setItem(KEY, JSON.stringify(v));
  } catch {
    /* storage blocked: the result page will show its empty state */
  }
}

export function loadClaimResult(): StoredClaimResult | null {
  try {
    const raw = window.sessionStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as StoredClaimResult) : null;
  } catch {
    return null;
  }
}

export function clearClaimResult(): void {
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
