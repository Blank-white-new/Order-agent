# Phase 3 verification matrix

| Control | Automated evidence | Gate |
|---|---|---|
| Four-class enum and explicit priority | `test_safety_decisions.py` | Refuse > handoff > confirm > draft |
| All 18 handoff reasons | parameterized decision tests | 18/18 |
| Refusal targets | parameterized refusal and Orchestrator tests | no order mutation |
| Layered/missing/contradictory confidence | decision and persistence tests | conservative result |
| Consecutive failure persistence | `test_confidence_persistence.py` | isolated and resettable |
| Handoff transition matrix | `test_handoff_workflow.py` | all allowed edges controlled; terminal states closed |
| Active-case idempotency/concurrency | service and database tests | one active case/session |
| Summary snapshot/redaction/failure | workflow and audit tests | no full contact/transcript/card data |
| Tenant/session/order constraints | `test_database_guards.py` | negative writes rejected |
| Migration cycle and metadata | Phase 2 and Phase 3 migration tests | empty/from-0003/down/re-up; 0 diff |
| Orchestrator safety hold | API/Orchestrator tests | handoff blocks submission; refuse has no order mutation |
| Development-only controls | API and Vitest tests | production hidden |
| Accessible truthful UI | `SafetyHandoffPanel.test.tsx` | state text, simulation warning, no real-human claim |
| Explicit-request cancellation preserves draft and requires reconfirmation | `test_handoff_cancellation.py`, API and Vitest tests | same order; old confirmation cannot replay |
| Mandatory-risk cancellation keeps safety hold | severe-allergy, cross-contamination, and abuse/security parameterized tests | continue/confirm/submit remain blocked |
| Concurrent cancellation is idempotent | service concurrency test and PostgreSQL CI | one terminal transition/event/version advance |
| Cancellation never produces merchant acceptance | lifecycle/event assertions and Vitest wording guards | zero fake acceptance and duplicate order |
| Phase 1 runtime policy | `run_phase1_runtime_policy_eval.py` | runnable classification 100% |
| Existing dialogue behavior | full backend, Phase 1 catalog, V3 runner | no regression |
| Offline/dependency guard | `pip check`, `pip-audit`, npm audit, offline env | zero high dependency findings; no live LLM |

## Required commands

```powershell
.\scripts\init_local_db.ps1
.\scripts\check_all.ps1 -Build
.\backend\.venv\Scripts\python.exe -B evaluation\run_dialogue_eval_v3.py --dataset evaluation\dialogues_v3.jsonl --fail-on-regression
.\backend\.venv\Scripts\python.exe evaluation\run_phase1_runtime_policy_eval.py
.\backend\.venv\Scripts\python.exe -m pip check
.\.tooling-venv\Scripts\python.exe -m pip_audit -r backend\requirements.lock.txt
```

PostgreSQL CI additionally runs the Phase 3 repository suite with `PHASE3_POSTGRES_URL`, concurrent handoff creation, tenant-negative writes, the migration cycle, runtime policy evaluation, and dependency audit. Windows CI runs the full backend/frontend suites, Phase 1 catalog, V3 57/57, runtime policy evaluation, typecheck, and production build.

## Runtime policy report semantics

The evaluator reads all 140 unchanged Phase 1 scenarios. It sends their structured policy metadata—not multilingual user text—to `SafetyDecisionService`, reports classification/reason/refusal matches, forbidden outcomes, and no-side-effect gates, and separately counts 105 scenarios whose non-`zh-CN` text parsing is not implemented. This is policy consistency evidence only.

## Local verification result

The cancellation-closeout local Windows run on 2026-07-17 produced:

- backend: 996 passed, 1 skipped; Phase 3 has 88 passing tests without removing prior coverage;
- frontend: 77 passed across 8 files; typecheck and production build passed;
- Phase 1 catalog: 140/140 unchanged;
- runtime policy: 140/140 classifications, 58/58 handoff reasons, 35/35 refusals, with every forbidden-outcome counter at zero;
- V3: 57/57, false mutation 0, confirmation bypass 0, live LLM trigger 0;
- cancellation lifecycle: old confirmation replay 0, mandatory hold incorrectly cleared 0, duplicate order 0, and cancellation-produced merchant acceptance 0;
- SQLite: empty upgrade, Phase 2-head upgrade, downgrade, re-upgrade, and metadata 0-diff passed;
- `pip check`, `pip-audit`, and npm high-severity audit: no broken requirements or known findings.

PostgreSQL 17.5 remains an authoritative CI gate; local verification does not claim a PostgreSQL result.
