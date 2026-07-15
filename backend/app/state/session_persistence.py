from __future__ import annotations

from copy import deepcopy

from app.state.session_state import DeliveryAddressCandidate, SessionState


SENSITIVE_STATE_KEYS = {
    "phone",
    "official_delivery_address",
    "pending_delivery_address_candidate",
    "last_address_mention",
}


def state_json_without_contact(state: SessionState, *, persistence_version: int | None = None) -> dict:
    payload = state.serializable()
    for key in SENSITIVE_STATE_KEYS:
        payload[key] = None
    payload["last_mutation_snapshot"] = _redact_nested_contact(payload.get("last_mutation_snapshot"))
    payload["pending_action"] = _redact_nested_contact(payload.get("pending_action"))
    if persistence_version is not None:
        payload["persistence_version"] = persistence_version
    return payload


def contact_from_state(state: SessionState) -> dict:
    pending = state.pending_delivery_address_candidate
    return {
        "official_delivery_address": state.official_delivery_address,
        "pending_delivery_address_json": pending.model_dump() if pending is not None else None,
        "phone": state.phone,
        "is_synthetic": state.is_synthetic,
    }


def apply_contact(state: SessionState, snapshot) -> None:
    if snapshot is None:
        return
    state.official_delivery_address = snapshot.official_delivery_address
    state.pending_delivery_address_candidate = (
        DeliveryAddressCandidate(**snapshot.pending_delivery_address_json)
        if snapshot.pending_delivery_address_json
        else None
    )
    state.phone = snapshot.phone


def _redact_nested_contact(value):
    if isinstance(value, dict):
        return {
            key: None if key in SENSITIVE_STATE_KEYS else _redact_nested_contact(item)
            for key, item in deepcopy(value).items()
        }
    if isinstance(value, list):
        return [_redact_nested_contact(item) for item in value]
    return value
