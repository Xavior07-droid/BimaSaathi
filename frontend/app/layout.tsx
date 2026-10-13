import type { Metadata, Viewport } from 'next';
import './globals.css';
import Providers from './providers';
import AppShell from '@/components/AppShell';

export const metadata: Metadata = {
  title: 'BimaSaathi',
  description: 'Understand and manage your health insurance policy, in your language.',
  manifest: '/manifest.json',
  applicationName: 'BimaSaathi',
  icons: {
    icon: [
      { url: '/favicon.ico', sizes: 'any' },
      { url: '/icons/icon.svg', type: 'image/svg+xml' },
      { url: '/icons/favicon-32.png', sizes: '32x32', type: 'image/png' },
    ],
    apple: [{ url: '/icons/apple-touch-icon.png', sizes: '180x180', type: 'image/png' }],
  },
  // iPhone "Add to Home Screen": opens full screen with its own title.
  appleWebApp: { capable: true, title: 'BimaSaathi', statusBarStyle: 'default' },
  formatDetection: { telephone: false }, // do not turn policy numbers into phone links
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: '#17645f',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
