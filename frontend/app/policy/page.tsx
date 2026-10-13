'use client';
import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { useTranslation } from 'react-i18next';
import EmptyState from '@/components/EmptyState';
import ErrorState from '@/components/ErrorState';
import LoadingState from '@/components/LoadingState';
import PolicyCard from '@/components/PolicyCard';
import { usePolicy } from '@/lib/queries';

function PolicyView({ id }: { id: string }) {
  const { t } = useTranslation();
  const { data, isLoading, isError, error, refetch, isRefetching } = usePolicy(id);

  if (isLoading) return <LoadingState cards={3} />;
  if (isError || !data) {
    return <ErrorState error={error} title={t('policy.errorTitle')} onRetry={() => void refetch()} retrying={isRefetching} />;
  }
  return <PolicyCard policy={data} />;
}

function PolicyRoute() {
  const { t } = useTranslation();
  const id = useSearchParams().get('id');
  if (!id) {
    return (
      <EmptyState
        icon="policy"
        title={t('policy.noIdTitle')}
        body={t('policy.noIdBody')}
        action={{ label: t('processing.goHome'), href: '/' }}
      />
    );
  }
  return <PolicyView id={id} />;
}

export default function PolicyPage() {
  return (
    <Suspense fallback={null}>
      <PolicyRoute />
    </Suspense>
  );
}
