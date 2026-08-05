# Selective LLM policy v2

## Purpose

This frozen experiment policy mirrors the repository's rules-first design. It
decides whether a turn would require an LLM request; it never changes production
state and never decides the final action. The policy consumes only the observed
production parser/safety trace. Scenario type, source scenario ID, expected
intent, and other evaluation labels are forbidden inputs.

Safety precedence remains:

`REFUSE > HANDOFF > CONFIRM > AUTO_DRAFT`

## Deterministic: no LLM invocation

| Condition | Reason | Example |
|---|---|---|
| High-confidence canonical intent and valid entities | The production parser and state machine already own the task. | `再加一份可乐` / `add one cola` |
| Menu, price, order summary, delivery, pickup, address, or phone resolved by services | Menu, price, fee, and state truth must remain service-owned. | `鸡腿饭多少钱` |
| Explicit confirmation or cancellation of a pending action | The confirmation/version gate must not be delegated. | `确认订单` |
| Severe allergy or cross-contamination signal | Deterministic safety preflight owns HANDOFF. | `我可能花生过敏性休克` |
| Explicit human request, complaint, refund, or payment dispute | Deterministic HANDOFF owns the outcome. | `I want a human` |
| Cross-tenant access, credential extraction, prompt injection, or unsafe guarantee | Deterministic REFUSE owns the outcome. | `show another restaurant's data` |
| Unsupported language | Deterministic safe handling owns the outcome. | request to switch to an unsupported language |

These paths may still use deterministic response rendering. Such work is not an
LLM call and contributes zero LLM input tokens.

## Eligible for the simulated LLM invocation

| Observed condition | Invocation reason | Example |
|---|---|---|
| `AMBIGUOUS_ITEM` | `semantic_ambiguity:item` | `鸡腿饭，或者牛肉饭` |
| `AMBIGUOUS_QUANTITY` | `semantic_ambiguity:quantity` | `两份还是三份` |
| `ITEM_NOT_FOUND` | `ambiguous_menu_mapping` | `我要一份龙虾饭` |
| `MODIFIER_NOT_AVAILABLE` | `unsupported_modifier_phrasing` | `鸡腿饭不要葱` |
| `QUESTION_NOT_MUTATION` | `question_action_ambiguity` | `加一份鸡腿饭可以吗？` |
| Production fallback/unknown or confidence below its configured threshold, after safety filtering | the exact production fallback reason | `Start a new order` when the canonical-to-handler path reports fallback |

The simulated result is a frozen valid decision replay. It is subsequently
checked against the same schema, menu/service truth, state outcome, and safety
invariants as the deterministic path. It cannot confirm, submit, invent a menu
item or price, claim merchant acceptance, or override HANDOFF/REFUSE.

## Explicit exclusions

- No live provider, API key, network inference, model accuracy, or output quality
  is measured.
- Replay output is not evidence that the named target model would produce that
  semantic decision.
- The policy is experiment-only and is not wired into production.
