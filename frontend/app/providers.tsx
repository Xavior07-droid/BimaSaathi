'use client';

import { useEffect, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { I18nextProvider } from 'react-i18next';
import { AuthProvider } from '@/lib/auth';
import i18n, { detectBrowserLang, readStoredLang, setLanguage } from '@/lib/i18n';

// App-wide providers: TanStack Query + i18next.
export default function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false } } }),
  );
  // Apply saved (or browser-detected) language after mount, so the static HTML and
  // the first client render match (both English) and there is no hydration warning.
  useEffect(() => {
    void setLanguage(readStoredLang() ?? detectBrowserLang());
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <I18nextProvider i18n={i18n}>
        <AuthProvider>{children}</AuthProvider>
      </I18nextProvider>
    </QueryClientProvider>
  );
}
