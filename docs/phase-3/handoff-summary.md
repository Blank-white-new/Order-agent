# Handoff summary and redaction

The versioned summary is generated from the structured `SessionState` and, when available, the Phase 2 persisted order and item snapshots. It contains:

- synthetic handoff, restaurant, and branch codes;
- locale and `summaryVersion`;
- item snapshots, authoritative stored minor-unit amounts, currency, and lifecycle status;
- sorted confirmed and unconfirmed field names;
- handoff reason, risk IDs, blocked actions, safe context codes, and forbidden actions;
- `isSynthetic: true` and the simulation-only context.

Phone and address are represented only as `***` presence masks. The summary contains no customer name, full phone, full address, raw text history, transcript, audio, card data, credential, or API key. Event payload validation also rejects sensitive key names and long digit sequences.

For a draft that has not produced a Phase 2 order, item amounts come from the service-backed values already stored in `SessionState`. Delivery fee remains zero and `delivery_fee` stays unconfirmed until the Phase 2 delivery service has produced an authoritative snapshot; the summary does not guess it.

The same persisted case state returns the same summary and version. Case creation commits before summary generation. If generation fails, the case remains auditable, transitions to `FAILED / SYSTEM_ERROR`, retains its order safety hold, and does not claim a connection.

Example shape:

```json
{
  "handoffId": "SIM-HO-...",
  "restaurantCode": "hk-sim-restaurant-a",
  "branchCode": "central",
  "locale": "zh-CN",
  "summaryVersion": 1,
  "order": {
    "items": [],
    "subtotalMinor": 0,
    "deliveryFeeMinor": 0,
    "totalMinor": 0,
    "currency": "HKD",
    "lifecycleStatus": "DRAFT"
  },
  "confirmedFields": [],
  "unconfirmedFields": ["address", "delivery_fee", "final_order", "phone"],
  "contact": {"phoneMasked": null, "addressMasked": null},
  "handoffReasonCode": "SEVERE_ALLERGY",
  "riskIds": ["RISK-009", "RISK-011", "RISK-013"],
  "blockedActions": ["SUBMIT_TO_MERCHANT"],
  "safeContext": ["SYNTHETIC_SIMULATION_ONLY", "REASON:SEVERE_ALLERGY"],
  "forbiddenActions": ["CLAIM_REAL_HUMAN_CONNECTED", "GUARANTEE_ALLERGEN_SAFE"],
  "isSynthetic": true
}
```
