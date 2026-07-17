# Safety decision model

`SafetyDecision` is a frozen structured value containing `classification`, stable `reason_code`, effective confidence, required confirmations, blocked actions, Phase 1 risk IDs, Phase 1 metric IDs, and an `explanation_code`. Natural-language response text is presentation only and is never the sole decision input.

## Classification

| Class | Permitted result | Mandatory guard |
|---|---|---|
| `AUTO_DRAFT` | Reversible, tenant-scoped draft operation | Blocks merchant submission, payment, and merchant-accepted claims |
| `CONFIRM` | Repeat the named fields and wait for explicit confirmation | Lists every required field; confidence alone cannot satisfy it |
| `HANDOFF` | Create/reuse a synthetic case and stop the high-risk goal | Requires a stable handoff reason and blocked actions |
| `REFUSE` | Reject the target operation | No order mutation; requires a stable refusal reason |

The forbidden states `AUTO_SUBMIT`, `AUTO_PAY`, `AUTO_REFUND`, and `AUTO_GUARANTEE_ALLERGEN_SAFE` do not exist in the enum, database checks, API, or state machine.

## Explicit priority

Rules are collected before classification and resolved in this order:

1. `REFUSE` / mandatory security block
2. `HANDOFF`
3. `CONFIRM`
4. `AUTO_DRAFT`

This is not dependent on rule iteration order. If a request combines card storage, severe allergy, and a draft operation, it is `REFUSE`. Per Phase 1 policy, the forbidden target is refused first; a legitimate service request may subsequently be handled as a separate handoff goal.

## Stable handoff reasons

`EXPLICIT_HUMAN_REQUEST`, `SEVERE_ALLERGY`, `CROSS_CONTAMINATION`, `REPEATED_MISUNDERSTANDING`, `AMBIGUOUS_ITEM`, `AMBIGUOUS_QUANTITY`, `UNVERIFIED_ADDRESS`, `PRICE_UNAVAILABLE`, `MENU_DATA_MISSING`, `COMPLAINT`, `REFUND_REQUEST`, `PAYMENT_DISPUTE`, `MERCHANT_REJECTED`, `MERCHANT_TIMEOUT`, `SYSTEM_FAILURE`, `LANGUAGE_UNSUPPORTED`, `ABUSE_OR_SECURITY`, and `REGULATED_ITEM`.

The database and API use these strings. Agents do not duplicate the mapping.

## Stable refusal reasons

`CROSS_TENANT_ACCESS`, `UNAUTHORIZED_ORDER_ACCESS`, `FORGE_MERCHANT_ACCEPTANCE`, `BYPASS_CONFIRMATION`, `CARD_DATA_STORAGE`, `UNSUPPORTED_SAFETY_GUARANTEE`, `INTERNAL_SECRET_EXTRACTION`, and `SECURITY_ATTACK`.

## Confirmation fields

The centralized rule set covers final order, address, phone, ambiguous item candidates, ambiguous quantity candidates, large modifications, delete-all, important notes, inferred values, delivery fee, and a changed order version. Contradictory confidence names are added to the field list. Missing confidence on a non-deterministic request requires intent confirmation.

## Audit boundary

Every persisted decision references a synthetic session and optional same-tenant order. It stores a confidence summary and structured IDs, not original text, raw audio, a full transcript, a full address, a phone number, or card data.
