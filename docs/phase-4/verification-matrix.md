# Verification matrix

| Requirement | Automated evidence |
|---|---|
| Locale detection, lock, unsupported scripts | `backend/tests/phase4/test_locale_normalization_numbers.py` |
| NFKC, control/zero-width removal, input limits, quantities | `test_locale_normalization_numbers.py` |
| Shared intent, item/alias/modifier matching, strict confirmation | `test_parser_catalog_safety.py` |
| 18 handoff and 8 refusal reasons across locales/mixed | `test_parser_catalog_safety.py` and Phase 4 evaluation |
| Published clone, three-language coverage, idempotency, sessions/holds | `test_menu_session_integration.py` |
| API compatibility, metadata, locale validation and trace redaction | `test_api_contract.py` |
| UI selector, mixed badge, localized safety/handoff, accessibility | `frontend/src/components/MultilingualText.test.tsx` |
| Dataset/catalog/message integrity | `scripts/validate_phase4_multilingual_catalog.py` |
| Raw-text execution and zero-error gates | `evaluation/run_phase4_multilingual_text_eval.py` |
| SQLite, Windows and PostgreSQL | `scripts/check_all.ps1` and `.github/workflows/ci.yml` |

Run locally:

```powershell
.\backend\.venv\Scripts\python.exe scripts\seed_phase4_multilingual_menu.py
.\backend\.venv\Scripts\python.exe scripts\validate_phase4_multilingual_catalog.py
.\scripts\check_all.ps1 -Build
.\backend\.venv\Scripts\python.exe -B evaluation\run_dialogue_eval_v3.py --dataset evaluation\dialogues_v3.jsonl --fail-on-regression
.\backend\.venv\Scripts\python.exe evaluation\run_phase1_runtime_policy_eval.py
.\backend\.venv\Scripts\python.exe evaluation\run_phase4_multilingual_text_eval.py
```

Phase 5 entry requires every Phase 3 and Phase 4 gate to remain green on Windows and PostgreSQL, no live LLM/translation service, and zero safety regression. Phase 5 may design provider interfaces and offline voice evaluation; it must not infer ASR/TTS/telephone readiness from these text results.
