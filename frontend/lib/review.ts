// Review dashboard helpers (F23). The score itself comes from the backend rules; here we only band it.
import type { ReviewAction, RiskLevel } from './types';

export const riskLevel = (score: number): RiskLevel => (score >= 70 ? 'high' : score >= 40 ? 'medium' : 'low');

export const ACTIONS: { value: ReviewAction; key: 'escalate' | 'clear' | 'moreInfo' }[] = [
  { value: 'Escalate', key: 'escalate' },
  { value: 'Clear', key: 'clear' },
  { value: 'Need more info', key: 'moreInfo' },
];

export const actionKey = (a: ReviewAction): 'escalate' | 'clear' | 'moreInfo' =>
  ACTIONS.find((x) => x.value === a)?.key ?? 'moreInfo';

export const LEVEL_STYLE: Record<RiskLevel, { cls: string; icon: string }> = {
  high: { cls: 'chip-danger', icon: '✕' },
  medium: { cls: 'chip-warning', icon: '!' },
  low: { cls: 'chip-success', icon: '✓' },
};
