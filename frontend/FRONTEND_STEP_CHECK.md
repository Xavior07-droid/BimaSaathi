# BimaSaathi frontend: F1 to F28 re-check

Checked against "Free-Tier Work Division" (Person F) and BUILD_PROMPT_FREE.md.
Method: code inspection + Chromium at 360x740 (en / hi / mr) + API contract test + production-mode build.

| Step | What | Result |
| --- | --- | --- |
| F1 | Next.js 14 + TypeScript + Tailwind, `output: 'export'`, ESLint | Pass. Static export builds 15 pages |
| F2 | Design tokens, Inter + Noto Sans Devanagari, min 16px, 360px base | Pass. Font-size audit: nothing under 16px |
| F3 | i18next en / hi / mr, switcher, choice saved | Pass. All 3 files have identical keys and placeholders |
| F4 | Typed API client + mock layer | Pass. `lib/api.ts`, `lib/mocks.ts` |
| F5 | App shell: header, bottom tabs, query-param routes, disclaimer footer | Pass. Disclaimer shows on all 10 screens |
| F6 | ServerWaking state for Render cold start | Pass. Contract test covers 503 then recover |
| F7 | Google sign-in, ID token on API calls, consent, privacy warning | Pass in code. Real Google sign-in needs your Firebase keys (demo login is used when keys are missing) |
| F8 | Home / upload: picker, camera, sample policy, validation | Pass |
| F9 | `/processing?id=` progress polling | Pass |
| F10 | Policy Card | Pass |
| F11 | Red Flags with "page X, clause Y" | Pass |
| F12 | Tap-to-explain jargon + EN/HI/MR toggle | Pass |
| F13 | Browser voice (speechSynthesis), no voice = text + notice | Pass in code. Real voices need a phone test |
| F14 | Ask chat UI, loading, errors | Pass |
| F15 | Voice input, en-IN / hi-IN / mr-IN | Pass in code. Needs a phone test (Chrome) |
| F16 | 3 chips, citations, fallback, disclaimer | Pass |
| F17 | Claim intake form | Pass. Validation errors tested |
| F18 | Document grid: previews, max 8, compression | Pass. 10 files picked, 8 kept |
| F19 | Result: score ring, found / missing / unclear, top 3 actions, share | Pass |
| F20 | Compare: selector, side-by-side table (scrolls inside its box), scenario inputs | Pass |
| F21 | Out-of-pocket cards, best fit, how calculated, "simplified estimate" | Pass. All labels rendered after running a scenario |
| F22 | Renewals: list, status chips, edit date, test reminder, calendar, FCM permission + token + service worker | Pass in code. Real push needs a phone test |
| F23 | Review dashboard: queue by risk, reasons drawer, "Human review required", actions, "Synthetic data" banner | Pass |
| F24 | Settings: language, Delete my data, consent info, install card | Pass |
| F25 | Empty, loading, error states | Pass on every screen that loads data. Settings and consent are static |
| F26 | PWA manifest, icons, installable | Pass. Manifest, 192 / 512 / maskable icons, install card. No offline cache (not in the free-tier plan) |
| F27 | Real API connection, CORS, cold start | Pass. Contract test 18/18 against the stub. Run `npm run test:contract:live` against Render once M deploys |
| F28 | 360px, 3 languages, accessibility, static export | Pass. Real-phone test still to do: see F28_TEST_CHECKLIST.md |

## Fixed during this re-check
- Form field borders were too faint (1.4:1). Now 4.7:1.
- `npm run build:prod` now blocks if `NEXT_PUBLIC_DEBUG=true`.

## Known limits
- Small inline glossary words are 26 to 28px tall (inline text, allowed by WCAG 2.5.8).
- Hindi and Marathi text has not been reviewed by a native speaker.
- Mock Ask answers are English only. Real answers follow the chosen language.
- `/debug` is built but does nothing unless `NEXT_PUBLIC_DEBUG=true`.
