# Frontend API notes (F4)

All network calls go through `lib/api.ts` (`api`), screens use the hooks in `lib/queries.ts`.
`NEXT_PUBLIC_USE_MOCKS=true` (default in `.env.local.example`) swaps in `lib/mocks.ts`.
Errors are `ApiError {status, code, message}`; `errorMessageKey(err)` returns an i18n key.

## Assumptions to confirm with M (docs/api.md, step M5)
| Item | Assumed |
|---|---|
| Error body | `{ "detail": { "error_code", "message" } }` (FastAPI) or the bare object |
| Ingest | `POST /api/ingest` multipart field `file` -> `{policy_id, status, cached}` |
| Sample policy | `POST /api/ingest/sample` -> same shape (backend returns sample_policy.json) |
| Status | `GET /api/policy/{id}/status` -> `{policy_id, status: uploading/reading/understanding/done/error}` |
| Suggestions | `GET /api/policy/{id}/suggestions?lang=` -> `string[]` |
| Claim check | multipart fields: policy_id, claim_type, admission_date, diagnosis, estimated_bill, documents (x8) |
| Reminders | `GET /api/reminders`, `PATCH /api/reminders/{policy_id}` body `{renewal_date}`, `POST /api/reminders/test` body `{policy_id}` |
| Consent | `POST /api/users/consent` body `{accepted: true}` |
| FCM token | `POST /api/users/fcm-token` body `{token}` |
| Review | `GET /api/fraud/claims` -> `{synthetic: true, claims[]}`; `POST .../{id}/action` body `{action}` |
| Auth | `Authorization: Bearer <Firebase ID token>`; wired in F7 via `setAuthTokenGetter` |

Any difference: change only `lib/api.ts` and `lib/types.ts`.

## F22 notes for M (push + reminders)
- `.ics` is built on the phone (`lib/ics.ts`): a plain download link cannot send the Bearer token. `GET /api/reminders/{id}/ics` is therefore unused by the UI (keep it if you want).
- Push: `lib/push.ts` asks permission, registers `/firebase-messaging-sw.js` (Firebase config passed as URL params), gets the FCM token with `NEXT_PUBLIC_FIREBASE_VAPID_KEY`, then `POST /api/users/fcm-token {token}`.
- The service worker shows data-only messages. Please send `data: {title, body, link}` (link like `/compare`) OR a `notification` + `webpush.fcm_options.link`; both work and never double-show.
- Days left and status chips are computed from `renewal_date` in the browser (`lib/renewal.ts`); `sent_flags` comes from the backend.
- `POST /api/reminders/test` should return `{sent: true|false}` (false if the user has no saved token).
- Hosting: serve `/firebase-messaging-sw.js` with `Cache-Control: no-cache` in firebase.json.

## F27: the contract the frontend calls (please make the backend match, or tell me what differs)
All paths are under `NEXT_PUBLIC_API_BASE`. Every `/api/*` call sends `Authorization: Bearer <Firebase ID token>`. `/health` sends no token.
Errors must look like FastAPI: `{"detail": {"error_code": "...", "message": "..."}}` (status 4xx/5xx). The UI maps `busy`/429/503, `unsupported_file_type`, `file_too_large` and 401 to translated messages.

| Call | Request | Success response |
|---|---|---|
| `GET /health` | none | `{status}` |
| `POST /api/ingest` | multipart `file` (pdf/jpg/png) | `{policy_id, status, cached}` |
| `POST /api/ingest/sample` (assumed) | `{}` | `{policy_id, status, cached}` |
| `GET /api/policy/{id}/status` | | `{policy_id, status: uploading\|reading\|understanding\|done\|error, error?}` |
| `GET /api/policy/{id}` | | PolicyBrain (see `lib/types.ts`) |
| `GET /api/policies` (assumed) | | `[{policy_id, insurer, policy_type, sum_insured, renewal_date}]` |
| `GET /api/policy/{id}/suggestions?lang=en\|hi\|mr` (assumed) | | `string[]` |
| `POST /api/policy/{id}/ask` | `{question, lang}` | `{answer, citations[{page,clause}], grounded, disclaimer}` |
| `POST /api/claim/check` | multipart: `policy_id, claim_type, admission_date, diagnosis, estimated_bill`, up to 8 x `documents` | `{score, rules[], documents[], top_actions[], disclaimer}` |
| `POST /api/compare` | `{policy_ids[2..3], scenario{days, room_rent_per_day, bill}}` | `{rows[], outcomes[], best_policy_id, recommendation, label}` |
| `GET /api/reminders` (assumed) | | `Reminder[]` |
| `PATCH /api/reminders/{id}` (assumed) | `{renewal_date}` | `Reminder` |
| `POST /api/reminders/test` | `{policy_id}` | `{sent}` |
| `POST /api/users/fcm-token` | `{token}` | `{ok}` |
| `POST /api/users/consent` (assumed) | `{accepted: true}` | `{ok}` |
| `DELETE /api/me/data` | | `{ok}` or 204 |
| `GET /api/fraud/claims` | | `{synthetic: true, claims[]}` |
| `POST /api/fraud/claims/{id}/action` | `{action: "Escalate"\|"Clear"\|"Need more info"}` | the updated claim |

"(assumed)" = not written in the build prompt; I guessed the shape. Tell me if yours differ and I change `lib/api.ts` only.

### CORS (the usual cause of "Network error" on a real phone)
Browsers send an OPTIONS preflight for JSON, `PATCH`, `DELETE` and the `Authorization` header. The FastAPI `CORSMiddleware` must allow:
- origins: `http://localhost:3000`, `https://bimasaathi-a78d4.web.app`, `https://bimasaathi-a78d4.firebaseapp.com` (no trailing slash, exact match)
- methods: `GET, POST, PATCH, DELETE, OPTIONS`
- headers: `Authorization, Content-Type`
- do not use `allow_origins=["*"]` together with `allow_credentials=True` (browsers reject it). We use Bearer tokens, not cookies, so credentials are not needed.
- Render free tier returns a 503 HTML page while waking up (no CORS headers). The app handles that by pinging `/health` first (`lib/serverStatus.ts`).

### Checking it
- `npm run stub` starts a stand-in server (`scripts/contract-server.mjs`) that follows this table. It is a reference, not the real backend.
- `npm run test:contract` runs the real client against the stub (18 checks: paths, bodies, multipart, auth header, errors, cold start, CORS preflight).
- `CONTRACT_BASE=https://<render-url> npm run test:contract:live` checks the deployed server: `/health` and the CORS preflight from each app origin.
