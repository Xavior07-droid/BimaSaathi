'use client';
// TanStack Query hooks: screens use these, never fetch directly.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api';
import type { AskRequest, Lang, ReviewAction, Scenario } from './types';

export const qk = {
  policy: (id: string) => ['policy', id] as const,
  policies: ['policies'] as const,
  status: (id: string) => ['policy-status', id] as const,
  suggestions: (id: string, lang: Lang) => ['suggestions', id, lang] as const,
  reminders: ['reminders'] as const,
  review: ['review'] as const,
};

export const usePolicy = (id: string | null) =>
  useQuery({ queryKey: qk.policy(id ?? ''), queryFn: () => api.getPolicy(id!), enabled: !!id });

export const usePolicies = () => useQuery({ queryKey: qk.policies, queryFn: () => api.listPolicies() });

/** Polls every 2s until the policy is done (or errored). Used by /processing. */
export const usePolicyStatus = (id: string | null) =>
  useQuery({
    queryKey: qk.status(id ?? ''),
    queryFn: () => api.getPolicyStatus(id!),
    enabled: !!id,
    staleTime: 0,
    gcTime: 0, // never reuse an old status when the same policy is processed again
    refetchInterval: (q) => (q.state.data?.status === 'done' || q.state.data?.status === 'error' ? false : 2000),
    retry: 5,
  });

export const useSuggestions = (id: string | null, lang: Lang) =>
  useQuery({ queryKey: qk.suggestions(id ?? '', lang), queryFn: () => api.getSuggestions(id!, lang), enabled: !!id });

export const useIngest = () => useMutation({ mutationFn: (file: File) => api.ingestPolicy(file) });
export const useIngestSample = () => useMutation({ mutationFn: () => api.ingestSample() });
export const useAsk = (id: string) => useMutation({ mutationFn: (req: AskRequest) => api.ask(id, req) });
export const useClaimCheck = () => useMutation({ mutationFn: api.checkClaim });
export const useCompare = () =>
  useMutation({ mutationFn: (req: { policy_ids: string[]; scenario: Scenario }) => api.compare(req) });

export const useReminders = () => useQuery({ queryKey: qk.reminders, queryFn: () => api.listReminders() });
export const useUpdateReminder = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; date: string }) => api.updateReminder(v.id, v.date),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.reminders }),
  });
};
export const useTestReminder = () => useMutation({ mutationFn: (id: string) => api.testReminder(id) });

export const useReviewClaims = () => useQuery({ queryKey: qk.review, queryFn: () => api.getReviewClaims() });
export const useReviewAction = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; action: ReviewAction }) => api.reviewAction(v.id, v.action),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.review }),
  });
};
export const useDeleteMyData = () => useMutation({ mutationFn: () => api.deleteMyData() });
