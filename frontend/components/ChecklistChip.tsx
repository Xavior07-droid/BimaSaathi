'use client';
// F19: status chip for documents (found / missing / unclear) and rules (pass / fail / at_risk).
// Always icon + colour + text.
import { useTranslation } from 'react-i18next';
import type { DocStatus, RuleStatus } from '@/lib/types';

type Status = DocStatus | RuleStatus;

const MAP: Record<Status, { cls: string; icon: string; key: string }> = {
  found: { cls: 'chip-success', icon: '✓', key: 'status.found' },
  pass: { cls: 'chip-success', icon: '✓', key: 'status.pass' },
  missing: { cls: 'chip-danger', icon: '✕', key: 'status.missing' },
  fail: { cls: 'chip-danger', icon: '✕', key: 'status.fail' },
  unclear: { cls: 'chip-warning', icon: '?', key: 'status.unclear' },
  at_risk: { cls: 'chip-warning', icon: '!', key: 'status.atRisk' },
};

export default function ChecklistChip({ status }: { status: Status }) {
  const { t } = useTranslation();
  const m = MAP[status] ?? MAP.unclear;
  return (
    <span className={`${m.cls} shrink-0`}>
      <span aria-hidden="true">{m.icon}</span> {t(m.key)}
    </span>
  );
}
