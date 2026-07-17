# Confidence policy

The runtime accepts optional `intent_confidence`, `item_confidence`, `quantity_confidence`, `modifier_confidence`, `address_confidence`, `phone_confidence`, and `overall_confidence`. Values are deterministic test or upstream metadata in the inclusive range 0–1; Phase 3 implements no real ASR confidence.

## Effective value

If `overall_confidence` is present it is used. Otherwise the minimum present layer is used, so a strong intent score cannot hide a weak quantity or address score. `contradictory_fields` is an explicit list and causes confirmation of those fields. Missing metadata is represented as missing, not fabricated.

## Central configuration

| Environment variable | Safe default | Meaning |
|---|---:|---|
| `SAFETY_HIGH_CONFIDENCE` | `0.85` | Reporting/high-confidence boundary; not authorization |
| `SAFETY_CONFIRM_THRESHOLD` | `0.65` | Lower values require confirmation |
| `SAFETY_HANDOFF_THRESHOLD` | `0.35` | Reserved conservative boundary; repeated failures determine handoff |
| `MAX_CONSECUTIVE_MISUNDERSTANDINGS` | `2` | Consecutive misunderstanding/correction/low-confidence limit |
| `MAX_CONFIRMATION_FAILURES` | `2` | Failed-confirmation limit |

Threshold order is validated at startup. Magic numbers are not repeated in agent code.

## Precedence and counters

- High confidence never bypasses final confirmation, severe-allergy handoff, cross-contamination controls, a human request, or refusal.
- One explicit low-confidence turn returns `CONFIRM`; reaching the configured consecutive threshold returns `HANDOFF / REPEATED_MISUNDERSTANDING`.
- A successful deterministic or high-confidence turn resets the low-confidence counter. `UNDERSTOOD` resets misunderstanding/correction counters; `CONFIRMATION_SUCCEEDED` resets confirmation failures.
- Counters are persisted per synthetic conversation session with restaurant/branch foreign keys. Tests prove different sessions and tenants do not share them.
- Missing confidence is conservative for the safety evaluation API. Ordinary rule-based Orchestrator results are marked deterministic and retain their own interpretation evidence.
