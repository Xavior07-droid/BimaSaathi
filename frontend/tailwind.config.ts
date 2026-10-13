import type { Config } from 'tailwindcss';

/**
 * BimaSaathi design tokens (F2).
 * Rules from the spec: mobile-first at 360px, minimum font size 16px,
 * large touch targets (>= 48px), status = icon + colour + text (never colour alone).
 * Every "fg" token below passes WCAG AA (4.5:1) on its paired "bg" token.
 */
const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}', './lib/**/*.{ts,tsx}'],
  theme: {
    // 360px is the base design width; `xs` lets us tweak for slightly larger phones.
    screens: {
      xs: '400px',
      sm: '640px',
      md: '768px',
      lg: '1024px',
    },
    // Minimum font size is 16px, so xs/sm intentionally equal base.
    fontSize: {
      xs: ['1rem', { lineHeight: '1.5rem' }],
      sm: ['1rem', { lineHeight: '1.5rem' }],
      base: ['1rem', { lineHeight: '1.625rem' }],
      lg: ['1.125rem', { lineHeight: '1.75rem' }],
      xl: ['1.25rem', { lineHeight: '1.75rem' }],
      '2xl': ['1.5rem', { lineHeight: '2rem' }],
      '3xl': ['1.875rem', { lineHeight: '2.25rem' }],
      '4xl': ['2.25rem', { lineHeight: '2.5rem' }],
    },
    extend: {
      colors: {
        // Trust-teal brand
        brand: {
          50: '#effaf8',
          100: '#d3f3ee',
          200: '#a8e6dd',
          300: '#72d2c6',
          400: '#3fb8ab',
          500: '#239d92',
          600: '#187d76',
          700: '#17645f',
          800: '#16504d',
          900: '#144341',
        },
        // Warm saffron accent (highlights, primary CTA on dark)
        accent: {
          50: '#fff8eb',
          100: '#ffecc6',
          300: '#ffc65c',
          500: '#f59e0b',
          600: '#d97706',
          700: '#b45309',
        },
        ink: {
          DEFAULT: '#0f172a', // body text
          soft: '#334155', // secondary text (AA on white)
          muted: '#475569', // tertiary text (AA on white)
        },
        surface: {
          DEFAULT: '#ffffff',
          alt: '#f6f8fa', // page background
          sunken: '#eef2f6',
          line: '#d5dde5', // decorative borders (cards, dividers)
          edge: '#64748b', // borders of form controls: 4.7:1 on white (WCAG 1.4.11 needs 3:1)
        },
        // Status pairs: bg + fg + border. Always render with icon + text label.
        success: { bg: '#e8f7ee', fg: '#14532d', line: '#86d4a4', solid: '#15803d' },
        warning: { bg: '#fff4d6', fg: '#7a3e00', line: '#f2c14e', solid: '#b45309' },
        danger: { bg: '#fdeaea', fg: '#7f1d1d', line: '#f1a3a3', solid: '#b91c1c' },
        info: { bg: '#e6f0fd', fg: '#0f3a7a', line: '#9fc2f2', solid: '#1d4ed8' },
        neutral: { bg: '#eef2f6', fg: '#1e293b', line: '#c5cfda', solid: '#475569' },
      },
      fontFamily: {
        // Latin first (Inter), then Devanagari (Hindi / Marathi), then system fallbacks.
        sans: [
          '"Inter Variable"',
          '"Noto Sans Devanagari Variable"',
          'system-ui',
          '-apple-system',
          '"Segoe UI"',
          'Roboto',
          'sans-serif',
        ],
      },
      spacing: {
        // Touch target helpers: min-h-touch / min-w-touch
        touch: '3rem', // 48px
        'touch-lg': '3.5rem', // 56px, primary actions
        'tab-bar': '4rem', // bottom tab bar height
        'safe-b': 'env(safe-area-inset-bottom)',
      },
      minHeight: { touch: '3rem', 'touch-lg': '3.5rem' },
      minWidth: { touch: '3rem' },
      borderRadius: { card: '1rem', pill: '999px' },
      boxShadow: {
        card: '0 1px 2px rgba(15,23,42,.06), 0 2px 8px rgba(15,23,42,.06)',
        sheet: '0 -4px 24px rgba(15,23,42,.16)',
      },
      maxWidth: { app: '30rem' }, // content column on larger screens
    },
  },
  plugins: [],
};

export default config;
