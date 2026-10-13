'use client';
// Bottom tab bar (mobile-first). Five tabs; settings lives in the header.
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useTranslation } from 'react-i18next';
import Icon, { type IconName } from './Icon';
import { useCurrentPolicyId } from '@/lib/currentPolicy';

interface Tab {
  key: string;
  icon: IconName;
  base: string; // path prefix used for the active state
  href: (policyId: string | null) => string;
}

const withId = (path: string) => (id: string | null) => (id ? `${path}?id=${encodeURIComponent(id)}` : path);

const TABS: Tab[] = [
  { key: 'home', icon: 'home', base: '/', href: () => '/' },
  // No policy yet -> send the user to Home to upload one.
  { key: 'policy', icon: 'policy', base: '/policy', href: (id) => (id ? `/policy?id=${encodeURIComponent(id)}` : '/') },
  { key: 'claim', icon: 'claim', base: '/claim', href: withId('/claim') },
  { key: 'compare', icon: 'compare', base: '/compare', href: () => '/compare' },
  { key: 'renewals', icon: 'bell', base: '/renewals', href: () => '/renewals' },
];

function isActive(pathname: string, base: string): boolean {
  const p = pathname.replace(/\/$/, '') || '/';
  if (base === '/') return p === '/' || p === '/processing';
  return p === base || p.startsWith(`${base}/`);
}

export default function Nav() {
  const { t } = useTranslation();
  const pathname = usePathname() ?? '/';
  const policyId = useCurrentPolicyId();

  return (
    <nav
      aria-label={t('shell.mainNav')}
      className="fixed inset-x-0 bottom-0 z-30 border-t border-surface-line bg-surface shadow-sheet"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      <ul className="mx-auto flex h-tab-bar max-w-app">
        {TABS.map((tab) => {
          const active = isActive(pathname, tab.base);
          return (
            <li key={tab.key} className="min-w-0 flex-1">
              <Link
                href={tab.href(policyId)}
                aria-current={active ? 'page' : undefined}
                className={`flex h-full flex-col items-center justify-center gap-0.5 px-0 text-base leading-tight ${
                  active ? 'font-semibold text-brand-800' : 'text-ink-soft'
                }`}
              >
                <span className={`flex h-8 w-14 items-center justify-center rounded-pill ${active ? 'bg-brand-100' : ''}`}>
                  <Icon name={tab.icon} />
                </span>
                <span className="max-w-full truncate">{t(`nav.${tab.key}`)}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
