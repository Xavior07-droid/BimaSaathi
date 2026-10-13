# F28 final test checklist (frontend)

Automated checks already run on the F27 build (Chromium, 360x740, mobile touch):
- Typecheck, lint, static export build: pass.
- en / hi / mr translation files have identical keys and placeholders.
- 10 screens x 3 languages: no sideways scroll, no console errors, every form field and button has a name.
- Claim flow: form errors, 8-image cap (10 selected, 8 kept), check, result: pass in all 3 languages.
- Ask flow: chips, answer, citations, disclaimer: pass in all 3 languages.
- Contrast: all text and status colours pass WCAG AA (4.5:1). Form-field borders raised to 4.7:1.
- No API keys or secrets found in the exported files.

Still to do by hand (needs real phones). Test on 3 phones: one Android Chrome, one low-end Android, one iPhone Safari.

## Per phone
- [ ] Open the Hosting URL on mobile data (not Wi-Fi). Server-waking message shows if Render is asleep.
- [ ] Switch EN / HI / MR: text fits, nothing cut off, Devanagari looks right.
- [ ] Sign in with Google, accept consent.
- [ ] Upload a sample policy (camera and gallery), reach the Policy Card.
- [ ] Listen button: plays in English. Hindi / Marathi: plays, or shows the "no voice installed" notice with text.
- [ ] Ask: tap a chip, then try the mic (Chrome only). Citation chip and disclaimer visible.
- [ ] Claim: fill form, add 3+ photos (take one with the camera), check, result shows score and checklist.
- [ ] Compare 2 policies: table scrolls sideways inside its box only.
- [ ] Renewals: allow notifications, press "test reminder", push arrives. Add to calendar downloads the .ics.
- [ ] Review: "Synthetic data" banner and "Human review required" label visible.
- [ ] Settings: Delete my data works.
- [ ] Install to home screen, open from the icon.
- [ ] Zoom the browser text to 200%: nothing overlaps.
- [ ] Turn on TalkBack / VoiceOver for one screen: buttons are read with sensible names.

## Before release
- [ ] `npm run build:prod` passes (mocks off, real API URL, Firebase keys set, debug off).
- [ ] Open the live site, DevTools Network: all calls go to the Render URL, none to localhost.
- [ ] CORS: no red errors in the console on the live site.
