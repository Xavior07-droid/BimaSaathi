# Folder Owners

| Code | Role | Owns |
|---|---|---|
| M | Main (Lead + Integrator) | .github/, render.yaml, firebase.json, firestore.rules, docs/, backend/app/main.py, config.py, auth.py, services/store.py, push.py, routers/users.py, cron.py, reminders.py, tests/test_cron.py |
| A | AI Backend | services/gemini.py, pdf.py, policy_brain.py, routers/ingest.py, policy.py, models/policy.py, prompts/, data/glossary.json, data/sample_policy.json, tests/test_ingest.py, test_ask.py |
| R | Rules and Data | services/rules.py, calculator.py, docs_check.py, fraud_rules.py, routers/claim.py, compare.py, fraud.py, models/claim.py, /data, tests/test_rules.py, test_calculator.py, test_claim.py |
| F | Frontend | /frontend (poora folder) |

## Rules
- Sirf apne folder ki files badlo. Doosre ki file badalni ho to pehle usse bolo.
- Har push se pehle: git pull --rebase origin main
- git push --force kabhi nahi.
- Koi key, .env ya service-account.json commit nahi.
- Step ka kaam khatam ho to docs/BimaSaathi build plan mein tick karo aur group mein batao.
