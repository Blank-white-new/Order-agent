# Response catalog

User-visible Phase 4 messages are keyed JSON catalogs in `backend/app/i18n/messages`. The three catalogs have identical keys for welcome, menu/query results, missing/ambiguous/unavailable items, quantity clarification, mutations, fulfilment, address/phone confirmation, order summary, customer confirmation, safety refusal/handoff, simulated-handoff warnings/failure, language switching/unsupported language, and merchant-not-integrated states.

The renderer uses the concrete `response_locale`. Item display names prefer that locale while item codes remain authoritative. It does not emit three repetitive translations. Cantonese templates use Hong Kong traditional written Cantonese; English templates use direct Hong Kong service English.

Missing keys or parameters fail in test/development. Production retries only the configured safe default locale, emits a metadata-only `MESSAGE_CATALOG_FALLBACK` audit event, and never returns a Python key. Templates do not claim that a real person is connected, a restaurant accepted an order, or food is allergen-safe.
