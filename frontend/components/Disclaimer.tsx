'use client';
import { useTranslation } from 'react-i18next';
import Icon from './Icon';

/** Shown at the bottom of every screen (spec: disclaimer footer on every screen). */
export default function Disclaimer({ showPrivacy = false }: { showPrivacy?: boolean }) {
  const { t } = useTranslation();
  return (
    <footer className="mt-8 rounded-card border border-surface-line bg-surface-sunken p-4 text-ink-soft" role="contentinfo">
      <p className="flex gap-2">
        <Icon name="info" className="mt-0.5 h-5 w-5 shrink-0" />
        <span>{t('disclaimer.general')}</span>
      </p>
      {showPrivacy && <p className="mt-2 pl-7">{t('disclaimer.privacy')}</p>}
    </footer>
  );
}
