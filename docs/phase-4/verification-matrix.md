# Verification matrix

| Requirement | Automated evidence |
|---|---|
| Locale detection, lock, unsupported scripts | `test_locale_normalization_numbers.py` |
| NFKC, control/zero-width removal, input limits, quantities | `test_locale_normalization_numbers.py` |
| Shared intent, item/alias/modifier matching, strict confirmation | `test_parser_catalog_safety.py` |
| Default Mandarin and all locales use canonical Orchestrator execution | `test_unified_canonical_path.py` and `test_api_contract.py` |
| Ambiguity/UNKNOWN cannot fall through to raw mutation | `test_unified_canonical_path.py` |
| Auto/Assisted input independence and reason denominators | `test_evaluator_independence.py` |
| 18 handoff and 8 refusal reasons across locales/mixed | `test_parser_catalog_safety.py` and Phase 4 evaluation |
| Published clone, three-language coverage, idempotency, sessions/holds | `test_menu_session_integration.py` |
| API compatibility, metadata, tenant binding and trace redaction | `test_api_contract.py` |
| UI selector, mixed badge, localized safety/handoff, accessibility | `frontend/src/components/MultilingualText.test.tsx` |
| 360 normalized-unique expressions and mixed-pattern coverage | `scripts/validate_phase4_multilingual_catalog.py` |
| Auto 360 main cases and 160-case locale specialty set | `run_phase4_multilingual_text_eval.py --mode auto` |
| Assisted concrete reply selection | `run_phase4_multilingual_text_eval.py --mode assisted` |
| SQL order/confirmation/idempotency checks | `test_database_tenant_evaluation.py` and Phase 4 runner |
| Real restaurant/branch/session/order/handoff/menu isolation | `test_database_tenant_evaluation.py` on SQLite and PostgreSQL |
| SQLite, Windows and PostgreSQL | `scripts/check_all.ps1` and `.github/workflows/ci.yml` |

Run locally:

```powershell
.\backend\.venv\Scripts\python.exe scripts\seed_phase4_multilingual_menu.py
.\backend\.venv\Scripts\python.exe scripts\validate_phase4_multilingual_catalog.py
.\backend\.venv\Scripts\python.exe evaluation\run_phase4_multilingual_text_eval.py --mode auto
.\backend\.venv\Scripts\python.exe evaluation\run_phase4_multilingual_text_eval.py --mode assisted
.\backend\.venv\Scripts\python.exe evaluation\run_phase4_multilingual_text_eval.py --mode both
.\scripts\check_all.ps1 -Build
.\backend\.venv\Scripts\python.exe -B evaluation\run_dialogue_eval_v3.py --dataset evaluation\dialogues_v3.jsonl --fail-on-regression
.\backend\.venv\Scripts\python.exe evaluation\run_phase1_runtime_policy_eval.py
```

Both CI jobs run diversity validation, canonical/evaluator/database tests, and separate Auto and Assisted evaluations. This PR remains Phase 4 only and provides no ASR/TTS/telephone readiness evidence.

## Verified local baseline

The final Windows/SQLite run on 2026-07-18 produced: backend `1194 passed, 1 skipped`; Phase 4 `198 passed`; Phase 3 `88 passed`; evaluator/database independence subset `7 passed`; Phase 1 catalog `140/140`; Phase 1 runtime policy `140/140`; V3 `57/57`; and frontend `84/84`. `pip check`, `pip-audit`, `npm audit`, TypeScript typecheck, and the production frontend build also passed. PostgreSQL evidence is provided by the required PostgreSQL 17.5 CI job rather than inferred from SQLite.
