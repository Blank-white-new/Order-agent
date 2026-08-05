# Token Efficiency v2 Error Analysis

## Dataset dependence

The 160 conversations contain 30 semantic template groups and 242 unique Phase 4 source scenarios across 868 turn references. No exact/normalized conversation was deleted, but repeated templates and expressions reduce effective semantic diversity. The primary report therefore shows both conversation and template-cluster bootstrap intervals.

## Source-label context mismatch

The Phase 4 labels were designed for isolated scenarios with their own setup state. When mapped diagnostically onto the assembled multi-turn trajectory, classification disagreed on **68/868** turns and the raw mutation boolean disagreed on **204/868** turns. These failures are retained. V2 does not silently rewrite Phase 4; it uses its intent/entity/blocking-safety labels where context remains valid and a separately frozen conversation-aware reference for mutation/final state.

## Semantic and locale errors

- Intent mismatches: 0 / 868.
- Item mismatches: 0 / 336.
- Quantity mismatches: 0 / 224.
- Modifier mismatches: 0 / 44.
- Locale mismatches: 34 / 868, by dataset locale: `{'mixed': 34}`. These are mostly mixed-language response-locale changes caused by accumulated conversation context; both architectures share them.

## Selective invocation distribution

System B invoked the replay provider 52/868 turns. Reasons: `{'production_fallback:fallback': 16, 'semantic_ambiguity:item': 4, 'semantic_ambiguity:quantity': 8, 'question_action_ambiguity': 8, 'ambiguous_menu_mapping': 8, 'unsupported_modifier_phrasing': 8}`. High-risk HANDOFF/REFUSE turns were excluded before invocation.

## Safety and expected-path errors

- Blocking safety violations: A=0, B=0.
- Confirmation bypass: A=0, B=0.
- Serious-allergy omission: A=0, B=0.
- False merchant acceptance: A=0, B=0.
- Unexpected duplicate mutation beyond the frozen path: A=0, B=0.
- Repeated normalized line identities: A=12, B=12. Twelve turn snapshots retain two deliberately requested portions that converge after replacement (for example, an existing beef-rice line plus a chicken-rice line explicitly replaced by beef rice); this is a representation diagnostic, not a duplicated action.
- Frozen-reference expected-path failures: A=0, B=0.

The absence of replay-reference failures is a deterministic regression/equivalence result, not a live-model quality claim.
