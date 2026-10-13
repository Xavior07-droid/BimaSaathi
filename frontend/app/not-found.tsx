'use client';
// F25: unknown address (also used by Firebase Hosting as 404.html in the static export).
import { useTranslation } from 'react-i18next';
import EmptyState from '@/components/EmptyState';

export default function NotFound() {
  const { t } = useTranslation();
  return <EmptyState icon="info" title={t('errors.notFoundTitle')} body={t('errors.notFoundBody')} action={{ label: t('errors.goHome'), href: '/' }} />;
}
