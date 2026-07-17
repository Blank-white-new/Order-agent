from __future__ import annotations

import asyncio
import os
import socket
from types import SimpleNamespace

import pytest

from evaluation import run_phase4_multilingual_text_eval as evaluator


BASE_ROW = {
    "scenario_id": "SPY-001",
    "locale": "mixed",
    "input": "runtime input",
    "restaurant_code": "hk-sim-restaurant-a",
    "branch_code": "central",
    "assisted_response_locale": "en-HK",
    "expected_detected_locale": "mixed",
    "expected_auto_response_locale": "zh-CN",
    "expected_intent": "ADD_ITEM",
    "expected_entities": {},
    "expected_classification": "AUTO_DRAFT",
    "expected_handoff_reason": None,
    "expected_refusal_reason": None,
    "expected_mutation": False,
    "expected_database_order_count": 0,
    "expected_active_confirmation_count": 0,
    "setup_inputs": [],
}


class FakeState:
    def __init__(self, classification="AUTO_DRAFT", reason=None):
        self.safety_classification = classification
        self.safety_reason_code = reason
        self.confirmation_valid = False
        self.current_order = []

    def serializable(self):
        return {
            "current_order": [],
            "fulfillment_type": "delivery",
            "official_delivery_address": None,
            "phone": None,
            "submitted": False,
            "submitted_order_id": None,
        }


class SpyService:
    def __init__(self):
        self.calls = []
        self.store = self

    def get(self, *_args, **_kwargs):
        return FakeState()

    async def handle_text_message(self, session_id, text, **kwargs):
        self.calls.append({"session_id": session_id, "text": text, **kwargs})
        classification, reason = {
            "handoff": ("HANDOFF", "SEVERE_ALLERGY"),
            "refuse": ("REFUSE", "CROSS_TENANT_ACCESS"),
        }.get(text, ("AUTO_DRAFT", None))
        state = FakeState(classification, reason)
        intent = {
            "handoff": "UNKNOWN",
            "refuse": "UNKNOWN",
        }.get(text, "ADD_ITEM")
        return {
            "raw_state": state,
            "trace": {
                "multilingual": {
                    "canonicalIntent": intent,
                    "entities": {},
                    "confirmationResult": "NOT_CONFIRMATION",
                },
                "safety": {"classification": classification, "reason_code": reason},
            },
            "detected_locale": "mixed",
            "dominant_locale": "zh-CN",
            "response_locale": "zh-CN",
            "response": "synthetic",
            "merchant_status": "NOT_INTEGRATED",
        }


def zero_database_snapshot(_runtime, _session_id):
    return {
        "orders": 0,
        "active_confirmations": 0,
        "duplicate_active_confirmations": 0,
        "duplicate_idempotency_records": 0,
    }


def test_auto_runtime_kwargs_never_contain_locale_or_ground_truth():
    poisoned = {
        **BASE_ROW,
        "expected_intent": "REFUND_REQUEST",
        "expected_detected_locale": "en-HK",
        "expected_classification": "REFUSE",
    }
    clean_kwargs = evaluator.build_request_kwargs(BASE_ROW, "auto", scenario_id="same")
    poisoned_kwargs = evaluator.build_request_kwargs(poisoned, "auto", scenario_id="same")

    assert clean_kwargs == poisoned_kwargs
    assert "locale" not in clean_kwargs
    assert "locale_hint" not in clean_kwargs
    assert "locale_locked" not in clean_kwargs
    assert not any(key.startswith("expected_") for key in clean_kwargs)


def test_assisted_runtime_uses_one_concrete_selection_without_duplicate_hint():
    kwargs = evaluator.build_request_kwargs(BASE_ROW, "assisted", scenario_id="assisted")

    assert kwargs["locale"] == "en-HK"
    assert kwargs["locale_locked"] is True
    assert "locale_hint" not in kwargs
    assert "mixed" not in kwargs.values()


def test_expected_fields_can_be_removed_without_blocking_runtime_kwargs():
    row = {
        key: value
        for key, value in BASE_ROW.items()
        if not key.startswith("expected_")
    }
    kwargs = evaluator.build_request_kwargs(row, "auto", scenario_id="no-ground-truth")

    assert kwargs["restaurant_code"] == "hk-sim-restaurant-a"
    assert kwargs["branch_code"] == "central"


def test_reason_denominators_only_include_relevant_scenarios(monkeypatch):
    monkeypatch.setattr(evaluator, "database_snapshot", zero_database_snapshot)
    rows = [
        dict(BASE_ROW),
        {
            **BASE_ROW,
            "scenario_id": "SPY-002",
            "input": "handoff",
            "expected_intent": "UNKNOWN",
            "expected_classification": "HANDOFF",
            "expected_handoff_reason": "SEVERE_ALLERGY",
        },
        {
            **BASE_ROW,
            "scenario_id": "SPY-003",
            "input": "refuse",
            "expected_intent": "UNKNOWN",
            "expected_classification": "REFUSE",
            "expected_refusal_reason": "CROSS_TENANT_ACCESS",
        },
    ]
    service = SpyService()
    metrics, failures, _performance = asyncio.run(
        evaluator.evaluate(rows, SimpleNamespace(service=service), "auto")
    )

    assert failures == []
    assert metrics.handoff_reason_checks == metrics.handoff_reason_matches == 1
    assert metrics.refusal_reason_checks == metrics.refusal_reason_matches == 1
    assert metrics.handoff_false_positives == 0
    assert metrics.refusal_false_positives == 0


def test_evaluator_executes_offline_and_live_llm_stays_zero(monkeypatch):
    monkeypatch.setattr(evaluator, "database_snapshot", zero_database_snapshot)
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("network access is forbidden in Phase 4 evaluation")
        ),
    )
    metrics, failures, _performance = asyncio.run(
        evaluator.evaluate(
            [dict(BASE_ROW)], SimpleNamespace(service=SpyService()), "auto"
        )
    )

    assert failures == []
    assert metrics.live_llm_triggers == 0
    assert os.environ["LLM_FALLBACK_MODE"] == "disabled"
    assert os.environ["ALLOW_LIVE_LLM"] == "false"
