# Going live (F27): switching from mocks to the real backend

1. **Backend up?** Open `https://<render-url>/health`. It can take up to a minute the first time (free tier sleeping).
2. **Check the server from outside the app** (needs the Render URL):
   `CONTRACT_BASE=https://<render-url> npm run test:contract:live`
   It checks `/health` and the CORS preflight for localhost and both Firebase Hosting origins. If a CORS line fails, M fixes `allow_origins` / `allow_methods` / `allow_headers` (see API_NOTES.md).
3. **Point the app at it** in `.env.local`:
   ```
   NEXT_PUBLIC_USE_MOCKS=false
   NEXT_PUBLIC_API_BASE=https://<render-url>
   NEXT_PUBLIC_DEBUG=true      # temporary: turns on /debug
   ```
   Restart `npm run dev` (env vars are read at start).
4. **Open `/debug`** on your laptop and on a real phone: press "Run checks". Each line should be green.
   - `HTTP 401` -> the Firebase token is not being accepted: M checks the project id / `FIREBASE_SERVICE_ACCOUNT`.
   - `Network error` / `network` with a green `/health` -> CORS (or http vs https).
   - `HTTP 503` -> the server is still waking up: wait and run again.
5. **Walk the real flow once:** upload a sample policy -> processing -> policy -> ask -> claim check -> compare -> renewals -> review -> delete my data. Anything that differs from API_NOTES.md: tell me the real response and I change `lib/api.ts` / `lib/types.ts` only.
6. **Build for Firebase Hosting:** `npm run build:prod` (refuses to build with mocks on, a localhost API, or missing Firebase keys), then `firebase deploy --only hosting`.
   Remove `NEXT_PUBLIC_DEBUG` for the final build.

Reference tools: `npm run stub` (stand-in server on :8099, set `NEXT_PUBLIC_API_BASE=http://localhost:8099`) and `npm run test:contract`.
