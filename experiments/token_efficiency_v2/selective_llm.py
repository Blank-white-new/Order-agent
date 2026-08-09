from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


ELIGIBLE_AMBIGUITIES = {
    "AMBIGUOUS_ITEM": "semantic_ambiguity:item",
    "AMBIGUOUS_QUANTITY": "semantic_ambiguity:quantity",
    "ITEM_NOT_FOUND": "ambiguous_menu_mapping",
    "MODIFIER_NOT_AVAILABLE": "unsupported_modifier_phrasing",
    "QUESTION_NOT_MUTATION": "question_action_ambiguity",
}

DETERMINISTIC_HIGH_RISK = {"HANDOFF", "REFUSE"}
DETERMINISTIC_CONTROL_INTENTS = {
    "CONFIRM_ORDER",
    "CANCEL_ORDER",
    "REQUEST_HUMAN",
    "COMPLAINT",
    "REFUND_REQUEST",
    "PAYMENT_DISPUTE",
}


@dataclass(frozen=True)
class InvocationDecision:
    invoked: bool
    reason: str


def decide_selective_invocation(result: dict[str, Any]) -> InvocationDecision:
    """Use production trace signals only; no scenario or expected labels."""
    trace = result.get("trace") or {}
    parsed = trace.get("multilingual") or {}
    safety = trace.get("safety") or {}
    state = result.get("state") or {}
    classification = safety.get("classification") or state.get("safety_classification")
    intent = parsed.get("canonicalIntent") or trace.get("finalIntent")

    if classification in DETERMINISTIC_HIGH_RISK:
        return InvocationDecision(False, f"deterministic_safety:{classification}")
    if intent in DETERMINISTIC_CONTROL_INTENTS:
        return InvocationDecision(False, f"deterministic_control:{intent}")

    for ambiguity in parsed.get("ambiguities") or []:
        reason = ELIGIBLE_AMBIGUITIES.get(str(ambiguity))
        if reason:
            return InvocationDecision(True, reason)

    production_reason = trace.get("llmFallbackReason")
    if production_reason:
        return InvocationDecision(True, f"production_fallback:{production_reason}")
    if intent in {"UNKNOWN", "fallback", "unknown"}:
        return InvocationDecision(True, "safe_unknown")
    return InvocationDecision(False, "deterministic_high_confidence")


def selective_prompt_sections(prompt: str, system_prompt: str) -> dict[str, str]:
    payload = json.loads(prompt)
    policy = {
        "task": payload.get("task"),
        "schema": payload.get("schema"),
        "privacy_rules": payload.get("privacy_rules"),
        "input_is_address_like": payload.get("input_is_address_like"),
    }
    history = {
        "address_present": payload.get("address_present"),
        "phone_present": payload.get("phone_present"),
        "pending_question": payload.get("pending_question"),
        "pending_action_type": payload.get("pending_action_type"),
        "order_summary": payload.get("order_summary"),
        "last_recommendations": payload.get("last_recommendations"),
        "recent_summary": payload.get("recent_summary"),
    }
    return {
        "system": system_prompt,
        "restaurant": "",
        "menu": json.dumps(payload.get("candidate_menu_items") or [], ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "policy": json.dumps(policy, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "history": json.dumps(history, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "current_input": str(payload.get("current_user_input") or ""),
        "full_prompt": prompt,
    }
