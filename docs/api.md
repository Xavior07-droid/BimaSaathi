# BimaSaathi API Contract (v1)

Yeh file M ki hai. Isse badalna ho to pehle M ko batao. F is contract se mocks banata hai, A aur R isi ke hisaab se endpoints likhte hain.

## Basics

- **Base URL:** `NEXT_PUBLIC_API_BASE` (local: `http://localhost:8080`, prod: Render URL). Sabhi paths `/api/...` se shuru hote hain, sirf `/health` bina `/api` ke.
- **Auth:** `Authorization: Bearer <Firebase ID token>`. Backend token verify karke `uid` nikalta hai.
  - Local dev ke liye: env `ALLOW_DEV_AUTH=true` ho to `Authorization: Bearer dev` chalega aur `uid` = `dev-user`. Production mein ye false rahega.
- **Format:** JSON (UTF-8). Uploads `multipart/form-data`. Dates `YYYY-MM-DD`, paise INR integers (Rs mein, decimal nahi).
- **Languages:** `en`, `hi`, `mr`.
- **Frontend routes (static export, query params):** `/policy?id=`, `/policy/ask?id=`, `/processing?id=`, `/claim/result?id=`.
- **Voice output:** backend mein koi TTS endpoint nahi. Frontend browser `speechSynthesis` use karta hai `plain_summary` text par.
- **MOCK mode:** `GEMINI_API_KEY` khali ho to `/api/ingest` `sample_policy.json` wala policy return karta hai (offline development ke liye).
- **Cold start:** Render free service so jaati hai. Pehli request 30-60 sec le sakti hai. Frontend `ServerWaking` state dikhaye aur `/health` se jagaye.

## Error format (har error mein)

```json
{ "error_code": "BAD_TYPE", "message": "Upload PDF, JPG or PNG" }
```

| HTTP | error_code | Matlab |
|---|---|---|
| 400 | `BAD_TYPE` | File type allowed nahi (sirf PDF, JPG, PNG) |
| 400 | `TOO_BIG` | 15 MB se badi file |
| 400 | `TOO_MANY` | 8 se zyada claim documents |
| 400 | `INVALID_INPUT` | Required field missing ya galat |
| 401 | `UNAUTHORIZED` | Token missing ya galat |
| 403 | `FORBIDDEN` | Doosre user ki policy |
| 404 | `NOT_FOUND` | Policy ya record nahi mila |
| 429 | `AI_BUSY` | Gemini free quota / rate limit, 1 minute baad retry |
| 502 | `AI_FAILED` | Extraction 3 baar fail hua |

## Endpoints

### Health
`GET /health` -> `{ "status": "ok", "mock_ai": true }` (auth nahi chahiye)

### 1. Upload aur policy (A)

**`POST /api/ingest`** (multipart, field `file`)
Response:
```json
{ "policy_id": "a1b2c3d4e5", "status": "done", "cached": false }
```
`cached: true` ka matlab same file pehle process ho chuki hai (Gemini call nahi hua). File server par store nahi hoti.

**`GET /api/policy/{id}/status`**
```json
{ "status": "reading" }
```
Values: `uploading`, `reading`, `understanding`, `done`, `failed`.

**`GET /api/policy/{id}`** -> Policy Brain:
```json
{
  "policy_id": "a1b2c3d4e5",
  "insurer": "Sample Health Insurance",
  "policy_no": "SH-2026-001234",
  "policy_type": "health",
  "holder_name": "Ramesh Patil",
  "start_date": "2026-04-01",
  "end_date": "2027-03-31",
  "renewal_date": "2027-03-31",
  "sum_insured": 500000,
  "premium": 14200,
  "waiting_periods": { "initial_days": 30, "pre_existing_months": 36, "specific_diseases_months": 24 },
  "room_rent_cap": { "value": 5000, "unit": "per_day" },
  "copay_percent": 10,
  "sub_limits": [ { "item": "Cataract", "limit": 40000, "source": { "page": 7, "clause": "5.3" } } ],
  "covered": [ { "text": "Hospitalisation over 24 hours", "source": { "page": 4, "clause": "3.1" } } ],
  "exclusions": [ { "text": "Cosmetic surgery", "source": { "page": 9, "clause": "6.2" } } ],
  "claim_requirements": {
    "cashless": ["claim form", "ID proof"],
    "reimbursement": ["claim form", "discharge summary", "final hospital bill", "investigation reports", "ID proof"],
    "intimation_deadline_hours": 48
  },
  "red_flags": [
    { "title": "Room rent cap", "why_it_matters": "Room Rs 5,000/day se mehnga hua to poore bill par proportionate cut lagega", "source": { "page": 5, "clause": "4.1" } }
  ],
  "plain_summary": { "en": "...", "hi": "...", "mr": "..." },
  "extraction_meta": { "model": "mock", "confidence": 0.9, "file_hash": "sha256...", "created_at": "2026-10-13T10:00:00Z" }
}
```
Rule: unknown value `null` hoti hai, kabhi guess nahi. `source` = `{ page, clause }`.

**`GET /api/policies`** -> `[ { policy_id, insurer, premium, renewal_date, ... } ]` (sirf current user ki)

### 2. Ask (A)

**`POST /api/policy/{id}/ask`**
```json
{ "question": "Kya knee surgery covered hai?", "lang": "hi" }
```
Response:
```json
{
  "answer": "Haan, 30 din ke waiting period ke baad covered hai.",
  "citations": [ { "page": 4, "clause": "3.1" } ],
  "grounded": true,
  "disclaimer": "Yeh sahayak uttar hai, insurer se confirm karein."
}
```
Agar answer policy mein nahi mila: `grounded: false`, `citations: []`, aur `answer` fixed fallback line (user ki language mein). Frontend tab "policy mein clear nahi hai" state dikhaye.

**`GET /api/policy/{id}/suggestions`** -> `["Is knee surgery covered?", "What is the waiting period?", "Is there a room rent limit?"]`

### 3. Claim check (R)

**`POST /api/claim/check`** (multipart)
- `claim`: JSON string
- `files`: 0 se 8 images (JPG/PNG), memory mein process, store nahi hote

`claim` ka JSON:
```json
{
  "policy_id": "a1b2c3d4e5",
  "claim_type": "reimbursement",
  "admission_date": "2026-10-05",
  "diagnosis": "knee replacement",
  "is_pre_existing": false,
  "is_specific_disease": false,
  "estimated_bill": 200000,
  "room_rent_per_day": 7000,
  "days": 5,
  "hours_to_intimate": 20
}
```
Response:
```json
{
  "score": 72,
  "rules": [
    { "rule_id": "R1", "title": "Waiting period", "status": "pass", "reason": "Waiting period completed", "clause": "2.1", "page": 3 },
    { "rule_id": "R4", "title": "Limits", "status": "at_risk", "reason": "Room rent Rs 7,000/day exceeds cap Rs 5,000/day - proportionate cut applies", "clause": "4.1", "page": 5 }
  ],
  "documents": [
    { "required": "discharge summary", "status": "found", "reason": "" },
    { "required": "final hospital bill", "status": "missing", "reason": "Not uploaded" },
    { "required": "ID proof", "status": "unclear", "reason": "Blurry image" }
  ],
  "actions": ["Get: final hospital bill (Not uploaded)", "Fix: Limits - ..."],
  "disclaimer": "This is not a guarantee of claim approval."
}
```
`rules[].status`: `pass | fail | at_risk | unknown`. `documents[].status`: `found | missing | unclear`. `actions` mein max 3 items.

### 4. Compare (R)

**`POST /api/compare`**
```json
{ "policy_ids": ["a1b2c3d4e5", "f6g7h8i9j0"], "scenario": { "days": 5, "room_rent_per_day": 5000, "bill": 200000 } }
```
Response:
```json
{
  "table": [
    {
      "policy_id": "a1b2c3d4e5", "insurer": "Sample Health", "premium": 14200, "sum_insured": 500000,
      "waiting_periods": { "initial_days": 30, "pre_existing_months": 36, "specific_diseases_months": 24 },
      "copay_percent": 10, "room_rent_cap": { "value": 5000, "unit": "per_day" },
      "key_exclusions": ["Cosmetic surgery", "Obesity treatment", "Dental"]
    }
  ],
  "scenario": { "days": 5, "room_rent_per_day": 5000, "bill": 200000 },
  "out_of_pocket": [
    { "policy_id": "a1b2c3d4e5", "insurer": "Sample Health", "proportion_factor": 1.0, "copay": 20000, "insurer_pays": 180000, "out_of_pocket": 20000, "how": "Room cap factor 1.00, co-pay 10%, sum insured cap applied. Simplified estimate." }
  ],
  "best_policy_id": "a1b2c3d4e5",
  "recommendation": "Is scenario mein Sample Health se aapko Rs 20,000 dena padega.",
  "label": "Simplified estimate"
}
```
Saare numbers code se aate hain. `recommendation` text Gemini likhta hai (numbers input se).

### 5. Reminders aur cron (M)

**`GET /api/reminders`**
```json
[ { "policy_id": "a1b2c3d4e5", "insurer": "Sample Health", "premium": 14200, "renewal_date": "2027-03-31", "days_left": 169, "status": "Active", "sent_flags": [] } ]
```
`status`: `Active | Expired`.

**`PATCH /api/reminders/{policy_id}`** body `{ "renewal_date": "2027-04-15" }` -> updated reminder.

**`POST /api/reminders/test?policy_id=...`** -> `{ "sent": true, "channel": "push" }` (turant ek push bhejta hai)

**`GET /api/reminders/{policy_id}/ics`** -> `text/calendar` file download.

**`POST /api/cron/reminders`** (GitHub Actions se; header `X-CRON-KEY`, user token nahi)
```json
{ "checked": 12, "sent": 3 }
```
Reminder 30, 15, 7 aur 1 din pehle jaata hai, `sent_flags` se duplicate nahi.

### 6. User aur privacy (M)

- `POST /api/users/fcm-token` body `{ "token": "..." }` -> `{ "ok": true }`
- `POST /api/users/consent` body `{ "version": "v1" }` -> `{ "ok": true }`
- `PUT /api/users/language` body `{ "language": "hi" }` -> `{ "ok": true }`
- `DELETE /api/me/data` -> `{ "deleted": true }` (user ke policies, reminders, qa, consent hata deta hai)

### 7. Review dashboard (R, synthetic data)

**`GET /api/fraud/claims`**
```json
{
  "synthetic_data": true,
  "claims": [
    {
      "claim_id": "C-1042", "hospital_id": "H-07", "invoice_no": "INV-8891", "bill_amount": 412000,
      "policy_start": "2026-09-20", "admission_date": "2026-10-02", "discharge_date": "2026-10-06",
      "risk_score": 75, "band": "High",
      "reasons": ["Admission within 30 days of policy start (waiting period)", "Same invoice number used in more than one claim"],
      "needs_human_review": true, "status": "Pending review"
    }
  ]
}
```
`band`: `High (>=60) | Medium (>=25) | Low`. List risk score ke hisaab se sorted.

**`POST /api/fraud/claims/{claim_id}/action`** body `{ "action": "Escalate" }` (values: `Escalate | Clear | Need more info`) -> `{ "claim_id": "C-1042", "status": "Escalate" }`

Hamesha: `needs_human_review` UI mein "Human review required" label ke saath dikhega. System kabhi claim reject nahi karta.

## Ownership

| Endpoints | Owner |
|---|---|
| `/health`, `/api/cron/*`, `/api/reminders*`, `/api/users*`, `/api/me/*`, auth | M |
| `/api/ingest`, `/api/policy*`, `/api/policies` | A |
| `/api/claim/*`, `/api/compare`, `/api/fraud/*` | R |
| Sabhi screens, mocks, API client | F |

## Change rule
Contract badalna ho to PR mein `docs/api.md` update karo aur group mein batao. Breaking change (field hataana/naam badalna) se pehle F aur related owner se baat karo.
