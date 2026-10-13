'use client';
// Wipes what the app keeps on this phone for the signed-in person (F24 "Delete my data").
// Language is a harmless preference and is kept. The consent record is not touched here:
// signing out afterwards returns the person to the sign-in screen.
import type { QueryClient } from '@tanstack/react-query';
import { clearClaimDraft } from './claimDraft';
import { clearClaimResult } from './claimResult';
import { clearCurrentPolicyId } from './currentPolicy';
import { clearPushFlag } from './push';

export function clearLocalAppData(queryClient: QueryClient): void {
  queryClient.clear(); // cached policies, reminders, chat answers
  clearClaimDraft();
  clearClaimResult();
  clearCurrentPolicyId();
  clearPushFlag();
}
