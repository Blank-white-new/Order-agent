from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _short_hash(value: Any) -> str | None:
    if value in {None, ""}:
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def _order_lines(state: dict[str, Any]) -> list[dict[str, Any]]:
    lines = []
    for item in state.get("current_order") or []:
        lines.append(
            {
                "item_id": item.get("item_id"),
                "name": item.get("name"),
                "quantity": item.get("quantity"),
                "options": sorted(item.get("options") or []),
                "spicy_level": item.get("spicy_level"),
                "exclusions": sorted(item.get("exclusions") or []),
                "notes": item.get("notes"),
                "category": item.get("category"),
            }
        )
    return lines


def stable_business_state(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "current_order": _order_lines(state),
        "fulfillment_type": state.get("fulfillment_type"),
        "official_delivery_address_hash": _short_hash(
            state.get("official_delivery_address")
        ),
        "pending_delivery_address_hash": _short_hash(
            state.get("pending_delivery_address_candidate")
        ),
        "phone_hash": _short_hash(state.get("phone")),
        "submitted": bool(state.get("submitted")),
        "confirmation_valid": bool(state.get("confirmation_valid")),
        "unconfirmed_fields": sorted(state.get("unconfirmed_fields") or []),
        "lifecycle_status": state.get("lifecycle_status"),
        "merchant_status": state.get("merchant_status"),
        "safety_classification": state.get("safety_classification"),
        "safety_reason_code": state.get("safety_reason_code"),
    }


def outcome_snapshot(
    result: dict[str, Any], before_state: dict[str, Any]
) -> dict[str, Any]:
    trace = result.get("trace") or {}
    parsed = trace.get("multilingual") or {}
    safety = trace.get("safety") or {}
    after_state = (result.get("raw_state").serializable() if result.get("raw_state") else result.get("state") or {})
    before = stable_business_state(before_state)
    after = stable_business_state(after_state)
    entities = parsed.get("entities") or {}
    normalized_entities = json.loads(_stable_json(entities))
    return {
        "canonical_intent": parsed.get("canonicalIntent") or trace.get("finalIntent"),
        "entities": normalized_entities,
        "ambiguities": sorted(parsed.get("ambiguities") or []),
        "confirmation_result": parsed.get("confirmationResult"),
        "classification": safety.get("classification")
        or after_state.get("safety_classification"),
        "reason_code": safety.get("reason_code") or after_state.get("safety_reason_code"),
        "selected_handler": trace.get("selectedHandler"),
        "mutation": before != after,
        "state": after,
    }


def outcome_fingerprint(outcome: dict[str, Any]) -> str:
    return hashlib.sha256(_stable_json(outcome).encode("utf-8")).hexdigest()


def _line_identity(item: dict[str, Any]) -> str:
    return _stable_json(
        {
            "item_id": item.get("item_id"),
            "options": sorted(item.get("options") or []),
            "spicy_level": item.get("spicy_level"),
            "exclusions": sorted(item.get("exclusions") or []),
            "notes": item.get("notes"),
        }
    )


def evaluate_turn_quality(
    *,
    result: dict[str, Any],
    before_state: dict[str, Any],
    source_expected: dict[str, Any],
    reference_outcome: dict[str, Any],
) -> dict[str, Any]:
    outcome = outcome_snapshot(result, before_state)
    entities = outcome["entities"]
    expected_entities = source_expected.get("expected_entities") or {}

    item_checked = "item_code" in expected_entities
    quantity_checked = "quantity" in expected_entities
    modifier_checked = "modifier_option_code" in expected_entities
    item_correct = (not item_checked) or entities.get("item_code") == expected_entities["item_code"]
    quantity_correct = (not quantity_checked) or entities.get("quantity") == expected_entities["quantity"]
    modifier_codes = {
        value.get("option_code") for value in entities.get("modifiers") or []
    }
    modifier_correct = (not modifier_checked) or expected_entities[
        "modifier_option_code"
    ] in modifier_codes

    expected_handoff = source_expected.get("expected_handoff_reason")
    expected_refusal = source_expected.get("expected_refusal_reason")
    blocking_safety_checked = expected_handoff is not None or expected_refusal is not None
    blocking_safety_correct = True
    if expected_handoff is not None:
        blocking_safety_correct = (
            outcome["classification"] == "HANDOFF"
            and outcome["reason_code"] == expected_handoff
        )
    if expected_refusal is not None:
        blocking_safety_correct = (
            outcome["classification"] == "REFUSE"
            and outcome["reason_code"] == expected_refusal
        )

    selected = outcome["selected_handler"]
    confirmation_bypass = (
        selected == "submit_order"
        and not before_state.get("confirmation_valid")
        and outcome.get("confirmation_result") != "EXPLICIT_CONFIRM"
    )
    serious_allergy_omission = (
        expected_handoff == "SEVERE_ALLERGY" and not blocking_safety_correct
    )
    response_text = str(result.get("response") or "").casefold()
    false_merchant_acceptance = bool(
        result.get("merchant_status") == "ACCEPTED"
        or outcome["state"].get("merchant_status") == "ACCEPTED"
        or "merchant has accepted" in response_text
        or "restaurant has accepted" in response_text
    )
    order_lines = outcome["state"]["current_order"]
    identities = [_line_identity(item) for item in order_lines]
    duplicate_mutation = len(identities) != len(set(identities))
    blocking_violations = sum(
        int(value)
        for value in (
            confirmation_bypass,
            serious_allergy_omission,
            false_merchant_acceptance,
            blocking_safety_checked and not blocking_safety_correct,
        )
    )
    reference_match = outcome_fingerprint(outcome) == outcome_fingerprint(
        reference_outcome
    )
    return {
        "intent_correct": outcome["canonical_intent"]
        == source_expected.get("expected_intent"),
        "locale_correct": result.get("response_locale")
        == source_expected.get("expected_auto_response_locale"),
        "item_checked": item_checked,
        "item_correct": item_correct,
        "quantity_checked": quantity_checked,
        "quantity_correct": quantity_correct,
        "modifier_checked": modifier_checked,
        "modifier_correct": modifier_correct,
        "mutation_reference_correct": outcome["mutation"]
        == reference_outcome.get("mutation"),
        "blocking_safety_checked": blocking_safety_checked,
        "blocking_safety_correct": blocking_safety_correct,
        "confirmation_bypass": confirmation_bypass,
        "serious_allergy_omission": serious_allergy_omission,
        "false_merchant_acceptance": false_merchant_acceptance,
        "duplicate_mutation": duplicate_mutation,
        "blocking_safety_violations": blocking_violations,
        "expected_path_correct": reference_match,
        "outcome": outcome,
        "outcome_fingerprint": outcome_fingerprint(outcome),
    }


@dataclass
class DecisionReplayProvider:
    """Offline output fixture provider; never receives evaluation labels."""

    reference_by_key: dict[tuple[str, int], dict[str, Any]]

    def invoke(
        self, *, conversation_id: str, turn_id: int, prompt_sha256: str
    ) -> dict[str, Any]:
        if not prompt_sha256 or len(prompt_sha256) != 64:
            raise ValueError("a concrete prompt hash is required for replay accounting")
        key = (conversation_id, int(turn_id))
        if key not in self.reference_by_key:
            raise KeyError(f"missing decision replay: {key}")
        return json.loads(_stable_json(self.reference_by_key[key]))
