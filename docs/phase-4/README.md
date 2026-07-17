# Phase 4: multilingual text ordering

Phase 4 adds a deterministic text layer for `zh-CN`, `yue-Hant-HK`, `en-HK`, and mixed/code-switched input. It normalizes text, detects locale, parses one shared set of canonical intents and authoritative menu codes, invokes the existing Phase 3 safety decision before allowed business operations, and renders the result in one concrete response locale. The Orchestrator and existing services remain the only mutation path.

`mixed` describes the input; it is never used as a response catalog. Written Cantonese is a separate `yue-Hant-HK` resource with Hong Kong traditional characters and colloquial forms. It is not simplified or treated as “traditional Mandarin”. The reviewed vocabulary is deliberately finite and does not claim complete coverage of Hong Kong Cantonese.

## Artifacts

- [Locale model](locale-model.md)
- [Text normalization and quantities](text-normalization.md)
- [Canonical intents](canonical-intents.md)
- [Versioned menu translations](menu-translations.md)
- [Code switching](code-switching.md)
- [Response catalog](response-catalog.md)
- [Safety integration](safety-integration.md)
- [Evaluation](evaluation.md)
- [Verification matrix](verification-matrix.md)

## Runtime

The text path is:

```text
raw text -> bounded NFKC normalization -> locale context -> reviewed lexicons
-> canonical intent/entities -> ambiguity and safety signals -> Phase 3 decision
-> existing Orchestrator/services -> localized message catalog
```

Locale detection confidence is trace metadata only. It never authorizes a mutation, confirms an order, clears a safety hold, changes an item code, or represents order accuracy. Explicit language switching changes the response locale without clearing the cart or advancing the draft version.

## Boundaries

This phase does not implement ASR, TTS, real-time voice, accent models, telephone lines, barge-in, audio recording, a real human, a real restaurant, POS, payment, real inventory, machine translation, generative free-form replies, complete Cantonese coverage, or European local languages. All menu, addresses, telephone-shaped fixtures, restaurants and customers are synthetic. Phase 5 may begin provider design and offline voice evaluation only while all Phase 4 text and Phase 3 safety gates remain green.
