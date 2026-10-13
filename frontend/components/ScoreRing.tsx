'use client';
// F19: Claim Readiness Score ring. The number is computed by the backend in code (never by the LLM).
// Status is shown as ring colour + icon + text label (never colour alone).
import { useTranslation } from 'react-i18next';

export type ScoreBand = 'good' | 'mid' | 'low';

export function scoreBand(score: number): ScoreBand {
  return score >= 75 ? 'good' : score >= 50 ? 'mid' : 'low';
}

const STYLE: Record<ScoreBand, { ring: string; chip: string; icon: string }> = {
  good: { ring: 'text-success-solid', chip: 'chip-success', icon: '✓' },
  mid: { ring: 'text-warning-solid', chip: 'chip-warning', icon: '!' },
  low: { ring: 'text-danger-solid', chip: 'chip-danger', icon: '✕' },
};

const R = 52;
const C = 2 * Math.PI * R;

export default function ScoreRing({ score }: { score: number }) {
  const { t } = useTranslation();
  const value = Math.max(0, Math.min(100, Math.round(Number.isFinite(score) ? score : 0)));
  const band = scoreBand(value);
  const s = STYLE[band];
  return (
    <div className="flex flex-col items-center gap-3">
      <div className="relative h-44 w-44" role="img" aria-label={t('claim.result.ringLabel', { score: value })}>
        <svg viewBox="0 0 120 120" className={`h-full w-full -rotate-90 ${s.ring}`} aria-hidden="true">
          <circle cx="60" cy="60" r={R} fill="none" strokeWidth="12" className="stroke-surface-sunken" />
          <circle
            cx="60"
            cy="60"
            r={R}
            fill="none"
            strokeWidth="12"
            strokeLinecap="round"
            stroke="currentColor"
            strokeDasharray={C}
            strokeDashoffset={C * (1 - value / 100)}
            className="motion-safe:transition-[stroke-dashoffset] motion-safe:duration-700"
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center" aria-hidden="true">
          <span className="text-4xl font-bold leading-none text-ink">{value}</span>
          <span className="text-ink-muted">/ 100</span>
        </div>
      </div>
      <p className={`${s.chip} text-lg font-semibold`}>
        <span aria-hidden="true">{s.icon}</span> {t(`claim.result.band.${band}`)}
      </p>
    </div>
  );
}
