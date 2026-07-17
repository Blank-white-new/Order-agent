# Phase 4 completion audit

## AUDIT-P4-001

- finding: Non-mixed evaluation passed both the correct locale and locale hint.
- impact: The previous locale result measured assisted behavior, not automatic detection.
- original_evidence: The former runner derived `requested_locale` and `locale_hint` from dataset ground truth for every non-mixed row.
- fix: Added separate Auto, Assisted, and Both modes. Auto runtime kwargs contain no locale fields; Assisted passes one concrete locale and a lock only.
- new_test: `test_evaluator_independence.py` poisons/removes expected labels and inspects runtime kwargs; Auto and Assisted run separately in both CI jobs.
- new_metric: Auto locale 360/360; Auto response locale 360/360; Assisted response locale 360/360.
- status: VERIFIED

## AUDIT-P4-002

- finding: Default Mandarin without locale fields could send raw text to the legacy path.
- impact: Ambiguity and UNKNOWN text could bypass the Phase 4 parser and mutate an order.
- original_evidence: `phase4_active` depended on explicit locale fields, non-Mandarin detection, or locale lock.
- fix: Removed locale-dependent path selection. Supported non-empty canonical text always reaches the existing Orchestrator; ambiguity, non-explicit confirmation, safety, and UNKNOWN stop before raw fallback.
- new_test: `test_unified_canonical_path.py` covers no-hint ADD, CHANGE, item/quantity ambiguity, allergy, confirmation version binding, UNKNOWN, locale parity, and four-locale lifecycle parity.
- new_metric: Canonical execution trace coverage passes for all clear supported-language scenarios; guarded cases have zero wrong mutation.
- status: VERIFIED

## AUDIT-P4-003

- finding: Each group used 45 expressions plus punctuation-only copies.
- impact: The claimed 360-row diversity was overstated.
- original_evidence: The generator loop appended `。` and ` !` to the same 45 strings.
- fix: Replaced the suffix loop with two reviewed paraphrase catalogs per locale and explicit mixed construction categories.
- new_test: The validator applies surface and normalized signatures and fails punctuation, spacing, case, courtesy-only, and normalized duplicates.
- new_metric: Surface unique 360/360; normalized unique 360/360; near-duplicate groups 0; punctuation duplicate groups 0; 45 categories per locale.
- status: VERIFIED

## AUDIT-P4-004

- finding: HANDOFF reason counted ordinary `None == None` rows as matches.
- impact: The reported denominator was 360 instead of relevant HANDOFF cases.
- original_evidence: The former runner compared conditional actual reason to `expected_handoff_reason` on every row.
- fix: Increment reason checks only when an expected HANDOFF reason exists; track ordinary-row false positives separately.
- new_test: `test_reason_denominators_only_include_relevant_scenarios`.
- new_metric: HANDOFF reason 64/64; handoff false positives 0 per mode.
- status: VERIFIED

## AUDIT-P4-005

- finding: REFUSE reason counted ordinary `None == None` rows as matches.
- impact: The reported denominator was 360 instead of relevant refusal cases.
- original_evidence: The former runner compared conditional actual reason to `expected_refusal_reason` on every row.
- fix: Increment reason checks only when an expected refusal reason exists; track ordinary-row false positives separately.
- new_test: `test_reason_denominators_only_include_relevant_scenarios`.
- new_metric: REFUSE reason 64/64; refusal false positives 0 per mode.
- status: VERIFIED

## AUDIT-P4-006

- finding: `duplicate_orders` only checked repeated cart item rows.
- impact: It did not establish database order or confirmation idempotency.
- original_evidence: The former runner compared `current_order` item IDs and never queried order tables.
- fix: Renamed the cart metric and added SQL checks for session orders, active confirmations, and idempotency records after every scenario plus explicit replay integration tests.
- new_test: `test_phase4_confirmation_uses_real_sql_and_remains_idempotent` runs on SQLite and PostgreSQL.
- new_metric: Duplicate order line items 0; duplicate database orders 0; duplicate active confirmations 0; duplicate idempotency records 0; database count matches 360/360.
- status: VERIFIED

## AUDIT-P4-007

- finding: `cross_tenant_leaks` primarily represented refusal classification.
- impact: Correct text classification did not prove database isolation.
- original_evidence: The former metric incremented only when two refusal reason strings did not match.
- fix: Split refusal classification from a 10-check real-access audit covering restaurant/branch session rebinding, order and handoff lookup, menu-version scope, disclosure, and no-write invariants.
- new_test: `test_phase4_real_cross_tenant_access_audit` and the API tenant-switch test run on SQLite and PostgreSQL.
- new_metric: Cross-tenant refusal errors 0; cross-tenant data-access leak failures 0/10 checks.
- status: VERIFIED

## AUDIT-P4-008

- finding: Phase 4 documentation and PR text used unqualified detection, duplicate-order, and cross-tenant claims.
- impact: Assisted detection and classification-only checks were presented as stronger evidence.
- original_evidence: The prior PR body stated locale/response/reason 360/360 and zero duplicate order/cross-tenant leak without layered definitions.
- fix: Updated Phase 4 documents with Auto/Assisted, independent denominators, cart/database distinction, refusal/access distinction, dataset limitations, and text-only scope. PR #13 is updated after final CI evidence.
- new_test: Documentation claims are tied to named runner fields and CI commands in `verification-matrix.md`.
- new_metric: Layered metrics in `evaluation.md`; no unqualified locale detection, duplicate-order, or cross-tenant claim remains.
- status: VERIFIED
