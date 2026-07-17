# Safety integration

`TextEntryService` remains the single text entry. It creates multilingual analysis, merges reviewed multilingual safety signals, calls the existing `SafetyDecisionService`, and only then supplies an allowed canonical command to the Orchestrator. The Phase 3 priority is unchanged:

```text
REFUSE > HANDOFF > CONFIRM > AUTO_DRAFT
```

All 18 `HandoffReasonCode` values have Mandarin, Cantonese, English and mixed-path tests. `LANGUAGE_UNSUPPORTED` comes from conservative locale detection. All eight `RefusalReasonCode` values have the same coverage. Phrases include human requests, severe allergy/anaphylaxis, cross-contamination, complaints/refunds/payment disputes, other-customer/order access, cross-tenant access, confirmation bypass, forged merchant acceptance, card storage, prompt/key extraction, unsupported allergy guarantees and security attacks.

ASCII phrases use token boundaries; Han phrases use reviewed substrings. Safety is not an exact-whole-string-only check. Mixed input preserves every matching risk signal. Locale confidence never downgrades a decision. Switching languages does not clear the reason, handoff identifier, frozen confirmation, blocked actions or mandatory hold.

Handoff remains a simulation and cannot claim staffing, connection or callback. `merchant_status` stays `NOT_INTEGRATED`; customer confirmation is not merchant acceptance. REFUSE and preflight CONFIRM/HANDOFF return without an order mutation.
