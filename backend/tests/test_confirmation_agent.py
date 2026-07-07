import pytest

from app.state.session_state import DeliveryAddressCandidate, OrderItem, SessionState
from .conftest import assert_trace_basics, send


def test_empty_order_confirm_cannot_submit(orchestrator):
    result = send(orchestrator, "确认")

    assert_trace_basics(result, agent="ConfirmationAgent", handler="confirm", intent="confirm")
    assert result["state"]["submitted"] is False
    assert "没有菜品" in result["response"]


def test_complete_delivery_order_confirm_includes_summary_and_submits(orchestrator):
    state = SessionState(
        current_order=[OrderItem(item_id="chicken_leg_rice", name="鸡腿饭", price=26, quantity=1, category="饭类")],
        fulfillment_type="delivery",
        official_delivery_address="中山大学南校园",
        phone="13812345678",
        stage="confirming",
    )
    result = send(orchestrator, "确认", state)

    assert_trace_basics(result, agent="ConfirmationAgent", handler="submit_order", intent="confirm")
    assert result["state"]["submitted"] is True
    assert "鸡腿饭" in result["response"]
    assert "26" in result["response"]


def test_pickup_order_confirm_does_not_need_address(orchestrator):
    state = SessionState(
        current_order=[OrderItem(item_id="cola", name="可乐", price=6, quantity=1, category="饮品")],
        fulfillment_type="pickup",
        stage="confirming",
    )
    result = send(orchestrator, "确认", state)

    assert_trace_basics(result, agent="ConfirmationAgent", handler="submit_order", intent="confirm")
    assert result["state"]["submitted"] is True


@pytest.mark.parametrize("message", ["确认订单", "确认下单", "确认提交", "就这样确认"])
def test_explicit_confirmation_phrases_submit_complete_order(orchestrator, message):
    state = SessionState(
        current_order=[OrderItem(item_id="cola", name="可乐", price=6, quantity=1, category="饮品")],
        fulfillment_type="pickup",
        stage="confirming",
    )

    result = send(orchestrator, message, state)

    assert_trace_basics(result, agent="ConfirmationAgent", handler="submit_order", intent="confirm")
    assert result["state"]["submitted"] is True


@pytest.mark.parametrize("message", ["取消订单", "取消下单", "不下单了"])
def test_explicit_cancellation_phrases_do_not_query_order_summary(orchestrator, message):
    state = SessionState(current_order=[OrderItem(item_id="cola", name="可乐", price=6, quantity=1, category="饮品")])

    result = send(orchestrator, message, state)

    assert_trace_basics(result, agent="ResponseAgent", handler="cancel", intent="cancel")
    assert result["state"]["submitted"] is False
    assert result["state"]["pending_action"]["type"] == "confirm_clear_order"


def test_pending_delivery_candidate_confirm_not_submit(orchestrator):
    state = SessionState(
        current_order=[OrderItem(item_id="cola", name="可乐", price=6, quantity=1, category="饮品")],
        pending_delivery_address_candidate=DeliveryAddressCandidate(
            raw="中山大学南校园",
            normalized="中山大学南校园",
            source="eta_question",
            confidence=0.95,
        ),
    )
    result = send(orchestrator, "可以", state)

    assert_trace_basics(result, agent="DeliveryAgent", handler="confirm_pending_address", intent="confirm_delivery_candidate")
    assert result["state"]["official_delivery_address"] == "中山大学南校园"
    assert result["state"]["submitted"] is False


def test_cancel_contexts(orchestrator):
    state = send(orchestrator, "推荐")["raw_state"]
    result = send(orchestrator, "算了", state)
    assert_trace_basics(result, agent="ResponseAgent", handler="cancel", intent="cancel")
    assert result["state"]["current_order"] == []

    state = SessionState(current_order=[OrderItem(item_id="cola", name="可乐", price=6, quantity=1, category="饮品")])
    result = send(orchestrator, "算了", state)
    assert_trace_basics(result, agent="ResponseAgent", handler="cancel", intent="cancel")
    assert result["state"]["current_order"][0]["name"] == "可乐"
    assert result["state"]["pending_action"]["type"] == "confirm_clear_order"


def test_confirm_pending_category_bulk_order(orchestrator):
    state = send(orchestrator, "饭类各来一份")["raw_state"]
    assert state.current_order == []
    assert state.pending_action["type"] == "confirm_order_category_items"

    result = send(orchestrator, "确认", state)

    assert_trace_basics(result, agent="ConfirmationAgent", handler="confirm_pending_action", intent="confirm")
    names = [item["name"] for item in result["state"]["current_order"]]
    assert names == ["牛肉饭", "黑椒牛肉饭", "鸡腿饭", "宫保鸡丁饭"]
    assert result["state"]["pending_action"] is None


def test_confirm_pending_conditional_order(orchestrator):
    state = send(orchestrator, "鸡腿饭多少钱？如果不贵就来一份")["raw_state"]
    assert state.current_order == []
    assert state.pending_action["type"] == "conditional_order"

    result = send(orchestrator, "确认", state)

    assert_trace_basics(result, agent="ConfirmationAgent", handler="confirm_pending_action", intent="confirm")
    assert result["state"]["current_order"][0]["name"] == "鸡腿饭"
    assert result["state"]["pending_action"] is None
