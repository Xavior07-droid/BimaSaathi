# Pull requests for Person R, steps R15-R25

Plan rule 3 says one PR = 1-3 steps, so this is split into four. Branch names follow rule 2.
Merge in this order (later ones use earlier ones). Paste each body into its PR.

---
## PR 1: `feature/R-15-16` Compare table and POST /api/compare (gate G3)
**Adds** `services/compare_table.py` (R15), `services/compare_summary.py`, `routers/compare.py` (R16), compare models in
`models/compare.py`, two synthetic sample policies in `data/sample_policies/`, `docs/compare.md`.
**Behaviour** 2-3 policies -> normalized table (premium, sum insured, 3 waiting periods, co-pay, room cap, key
exclusions) + out-of-pocket per policy + "how calculated" + best fit + 3-4 line recommendation. All numbers come
from code; AI text is dropped if it contains a number the calculator did not produce.
**Needs from others** Main: `include_router(compare.router)` in `main.py`. Person A: `store.get_policy`, and A25
`compare_recommendation(facts)` (the code-written text is used until then).
**Tests** `test_compare_table.py`, `test_compare_summary.py`, `test_compare.py` (HTTP, needs fastapi).

---
## PR 2: `feature/R-17-19` Synthetic claims, optional BigQuery loader, benchmarks
**Adds** `data/seed.py`, `data/synthetic_claims.csv`, `data/ground_truth.csv` (R17), `data/bq_load_optional.py` (R18,
optional, not used by the app, no billing needed), `services/benchmarks.py` (R19).
**Behaviour** 200 invented claims with 16 planted anomalies (19 claims should be flagged). `seed.py` refuses to
write data unless the five rules flag exactly the planted claims. `python data/seed.py --check` fails if files drift.
**Note** `ground_truth.csv` is the fraud answer key. Person A's extraction sheet (A4) needs a different file name.
**Tests** `test_seed_data.py`, `test_bq_load.py` (fake client; one real BigQuery run still to be done by a human),
`test_benchmarks.py`.

---
## PR 3: `feature/R-20-24` Fraud rules, review API, rules page
**Adds** `services/fraud_rules.py`, `models/fraud.py` (R20), fraud router/rewrite/peer check (R21-R23), and
`docs/rules.md` + `tests/test_rules_doc.py` (R24).
**Behaviour** F1-F5 each add fixed points (F1 40, F2 50, F3 25, F4 45, F5 20, capped at 100). Score and level come
from rules only; wording is neutral; every item says "Human review required"; nothing is rejected automatically.
**Check before merging** the F1-F5 "to confirm" cells in `docs/rules.md` section 4 against the real constants.
**Tests** `test_fraud_rules.py` (also checks the flags equal `ground_truth.csv`), `test_rules_doc.py`.

---
## PR 4: `feature/R-25` CI, coverage, lint
**Adds** `.github/workflows/ci.yml`, `backend/pytest.ini`, `backend/.coveragerc`, `backend/requirements-dev.txt`.
**CI steps** install -> lint (real errors only: `ruff --select E9,F`) -> tests with coverage -> coverage report ->
90% gate on the Rules and Data lane files -> check `data/seed.py --check`.
**Also** removes 6 unused imports found by the linter.
**Merge note** if `ci.yml` already has a frontend or deploy job, keep it and add the `backend` job from this file.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01Qz7gVu4fJbyc89A9Us9mHM
