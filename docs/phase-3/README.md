# Phase 3: Safety decision and simulated handoff core

Phase 3 turns the Phase 1 `AUTO_DRAFT`, `CONFIRM`, `HANDOFF`, and `REFUSE` policy into a deterministic, persistent, auditable runtime control. It builds on the Phase 2 tenant/session/order model and never connects to a real human, phone network, restaurant, POS, payment service, or customer record.

## Runtime boundary

The Orchestrator remains the only ordering entry point. `TextEntryService` evaluates narrow safety signals before an order operation and records a post-operation policy result for ordinary deterministic draft behavior. `REFUSE` performs no order mutation. `HANDOFF` creates or reuses a synthetic case, invalidates the current confirmation, places a safety hold on an already confirmed local order, and blocks merchant submission. `CONFIRM` does not authorize external submission. `AUTO_DRAFT` is limited to reversible draft behavior.

The narrow safety phrase detector is a guard, not a multilingual parser. The Phase 1 runtime evaluation supplies structured scenario metadata directly to the policy engine. It reports unsupported language parsing separately and does not claim Cantonese, English, mixed-language, ASR, or TTS support.

## Artifacts

- [Safety decision model](safety-decision-model.md)
- [Confidence policy](confidence-policy.md)
- [Handoff state machine](handoff-state-machine.md)
- [Handoff summary](handoff-summary.md)
- [Failure policy](failure-policy.md)
- [Synthetic API](api.md)
- [Verification matrix](verification-matrix.md)

## Traceability

The core implements Phase 1 `REQ-001`, `REQ-005` through `REQ-016`, `REQ-018` through `REQ-020`, and `REQ-023` through `REQ-030`. Decision records carry the scenario-provided `RISK-*` and `METRIC-*` identifiers; built-in safety rules add the applicable Phase 1 identifiers such as `RISK-009`, `RISK-013`, `RISK-026`, `RISK-029`, `RISK-033`, `RISK-046`, `METRIC-001`, `METRIC-002`, `METRIC-005`, `METRIC-006`, `METRIC-011`, `METRIC-012`, and `METRIC-014`.

Phase 2 remains authoritative for tenants, published menus, prices, modifiers, allergen declarations, delivery fees, session versions, confirmation fingerprints, order snapshots, and lifecycle events. Phase 3 adds a separate safety hold; a simulated handoff resolution never means `MERCHANT_ACCEPTED`.

The cancellation closeout uses the existing Phase 3 schema. Revision `20260717_0004` remains the migration head; no empty `20260717_0005` migration is created.

## Cancelling a simulated handoff

Cancelling `EXPLICIT_HUMAN_REQUEST` cancels only the simulated queue. The existing draft and items remain, a hold caused only by that reason is cleared, and a previously confirmed local order returns to `DRAFT`. The old confirmation stays invalid, its draft version cannot be replayed, menu/price/availability are checked again, and the customer must explicitly reconfirm. Reconfirmation reuses that local order rather than creating a duplicate and never means merchant acceptance.

Every other HANDOFF reason is mandatory for cancellation purposes. Cancelling its simulated case records `CANCELLED` but retains the current reason and safety hold. “Continue myself” cannot bypass the guard, and neither confirmation nor submission is allowed. A failed simulated handoff also retains the draft, invalid confirmation, and hold; it does not automatically send the order, promise a callback, or create a real-human connection.

## Non-goals

- Real human-agent availability, staffing, SLA, or connection
- SIP/PSTN, callbacks, SMS, or real telephone numbers
- Real POS, payment, refund, inventory, or merchant acceptance
- Real customer names, addresses, calls, recordings, transcripts, or card data
- Live LLM calls or multilingual text/voice parsing
- A guarantee that any food is allergen-safe or free from cross-contamination

## Phase 4 entry conditions

Phase 4 may add broader deterministic ordering behavior only after the Phase 3 policy gates remain green: zero confirmation bypass, erroneous automatic submission, serious-allergy omission, cross-tenant handoff leakage, and fake merchant acceptance. A future real-provider design additionally requires approved identity, privacy, availability, retention, incident, and truthful-status controls; the simulation provider is not evidence that those controls exist.
