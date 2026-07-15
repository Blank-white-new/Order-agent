from __future__ import annotations

import pytest

from app.models.schemas import Interpretation
from app.state.session_state import DeliveryAddressCandidate, OrderItem, SessionState
from .conftest import send


def _submitted_pickup_order(orchestrator) -> SessionState:
    state = SessionState(
        current_order=[
            OrderItem(
                item_id="chicken_leg_rice",
                name="鸡腿饭",
                price=26,
                quantity=1,
                category="饭类",
            )
        ],
        fulfillment_type="pickup",
        stage="confirming",
    )
    result = send(orchestrator, "确认", state)
    assert result["trace"]["selectedHandler"] == "submit_order"
    assert state.submitted is True
    assert state.submitted_order_id
    return state


def _locked_order_snapshot(state: SessionState) -> dict:
    data = state.serializable()
    return {
        "current_order": data["current_order"],
        "fulfillment_type": data["fulfillment_type"],
        "official_delivery_address": data["official_delivery_address"],
        "pending_delivery_address_candidate": data["pending_delivery_address_candidate"],
        "phone": data["phone"],
        "submitted": data["submitted"],
        "submitted_order_id": data["submitted_order_id"],
    }


def test_submitted_order_cannot_add_item(orchestrator):
    state = _submitted_pickup_order(orchestrator)
    order_id = state.submitted_order_id
    before = _locked_order_snapshot(state)

    result = send(orchestrator, "再来一份可乐", state)

    assert _locked_order_snapshot(state) == before
    assert state.submitted is True
    assert state.submitted_order_id == order_id
    assert result["trace"]["selectedHandler"] == "submitted_order_locked"
    assert result["trace"]["stateMutationRejectedReason"] == "submitted_order_locked"
    assert result["trace"]["lifecycleReason"] == "new_order_required"
    assert "不能继续修改" in result["response"]
    assert "重新下单" in result["response"]


@pytest.mark.parametrize(
    "message",
    [
        "把鸡腿饭删了",
        "鸡腿饭改成两份",
        "把鸡腿饭换成可乐",
        "地址改成测试园区二号楼",
    ],
)
def test_submitted_order_rejects_item_and_delivery_changes(orchestrator, message):
    state = _submitted_pickup_order(orchestrator)
    before = _locked_order_snapshot(state)

    result = send(orchestrator, message, state)

    assert _locked_order_snapshot(state) == before
    assert result["trace"]["stateMutationAllowed"] is False
    assert result["trace"]["stateMutationRejectedReason"] == "submitted_order_locked"
    assert "不能继续修改" in result["response"]


@pytest.mark.parametrize("message", ["确认订单", "就这些", "可以下单了"])
def test_repeated_confirmation_is_idempotent(orchestrator, monkeypatch, message):
    state = _submitted_pickup_order(orchestrator)
    before = state.serializable()
    order_id = state.submitted_order_id

    def fail_duplicate_submit(_state):
        raise AssertionError("submitted order must not be submitted twice")

    monkeypatch.setattr(orchestrator.order_service, "submit_order", fail_duplicate_submit)
    result = send(orchestrator, message, state)

    assert state.serializable() == before
    assert state.submitted_order_id == order_id
    assert result["trace"]["finalIntent"] == "confirm"
    assert result["trace"]["selectedHandler"] == "order_already_submitted"
    assert result["trace"]["stateMutationRejectedReason"] == "order_already_submitted"
    assert order_id in result["response"]
    assert "已由顾客确认并保存" in result["response"]
    assert "尚未发送给真实餐厅" in result["response"]


@pytest.mark.parametrize("message", ["重新下单", "再来一单", "开始新订单", "新订单", "重新点一份"])
def test_explicit_new_order_starts_from_clean_state(orchestrator, message):
    state = _submitted_pickup_order(orchestrator)
    state.last_recommendations = [{"name": "牛肉饭"}]
    state.preferences = {"avoid": ["牛肉"], "options": ["清淡"]}
    state.official_delivery_address = "测试园区一号楼"
    state.pending_delivery_address_candidate = DeliveryAddressCandidate(
        raw="测试园区二号楼",
        normalized="测试园区二号楼",
        source="test",
        confidence=1.0,
    )
    state.pending_action = {"type": "test_pending"}
    state.phone = "13800000000"

    result = send(orchestrator, message, state)

    assert state.serializable() == SessionState().serializable()
    assert result["trace"]["finalIntent"] == "start_new_order"
    assert result["trace"]["lifecycleReason"] == "new_order_started"
    assert result["trace"]["orderBefore"]
    assert result["trace"]["orderAfter"] == []

    add_result = send(orchestrator, "来一份可乐", state)
    assert [item["name"] for item in add_result["state"]["current_order"]] == ["可乐"]
    assert add_result["state"]["submitted"] is False
    assert add_result["state"]["submitted_order_id"] is None


def test_final_order_id_alone_also_locks_order(orchestrator):
    state = SessionState(
        current_order=[OrderItem(item_id="cola", name="可乐", price=6, category="饮品")],
        submitted=False,
        submitted_order_id="MOCK-FINAL-ORDER",
    )
    before = state.serializable()

    result = send(orchestrator, "可乐改成两份", state)

    assert state.serializable() == before
    assert result["trace"]["stateMutationRejectedReason"] == "submitted_order_locked"


def test_confirmation_agent_has_its_own_idempotency_guard(orchestrator, monkeypatch):
    state = _submitted_pickup_order(orchestrator)
    before = state.serializable()

    def fail_duplicate_submit(_state):
        raise AssertionError("submitted order must not be submitted twice")

    monkeypatch.setattr(orchestrator.order_service, "submit_order", fail_duplicate_submit)
    result = orchestrator.confirmation_agent.handle(
        Interpretation(intent="confirm", confidence=1.0, source="rule"),
        state,
    )

    assert result["handler"] == "order_already_submitted"
    assert result["patch"] == {}
    assert state.serializable() == before
