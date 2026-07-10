from __future__ import annotations

from app.state.session_state import OrderItem, SessionState
from .conftest import assert_trace_basics, send


def _single_order_item(result: dict) -> dict:
    order = result["state"]["current_order"]
    assert len(order) == 1
    return order[0]


def test_order_food_with_spicy_level(orchestrator):
    result = send(orchestrator, "我要一份鸡腿饭少辣")

    item = _single_order_item(result)
    assert_trace_basics(result, agent="OrderAgent", handler="order_food", intent="order_food")
    assert item["name"] == "鸡腿饭"
    assert item["spicy_level"] == "少辣"


def test_order_food_with_exclusion(orchestrator):
    result = send(orchestrator, "我要一份宫保鸡丁不要花生")

    item = _single_order_item(result)
    assert item["name"] == "宫保鸡丁饭"
    assert item["exclusions"] == ["花生"]


def test_order_food_with_note(orchestrator):
    result = send(orchestrator, "一份鸡腿饭，米饭多一点")

    item = _single_order_item(result)
    assert item["name"] == "鸡腿饭"
    assert item["notes"] == "米饭多一点"


def test_update_recent_item_modifier_without_adding_item(orchestrator):
    state = send(orchestrator, "先来一份鸡腿饭")["raw_state"]

    result = send(orchestrator, "不要香菜", state)

    item = _single_order_item(result)
    assert_trace_basics(result, agent="OrderAgent", handler="update_item_option", intent="update_item_option")
    assert item["name"] == "鸡腿饭"
    assert item["quantity"] == 1
    assert item["exclusions"] == ["香菜"]


def test_update_named_item_spicy_level(orchestrator):
    state = SessionState(current_order=[OrderItem(item_id="chicken_leg_rice", name="鸡腿饭", price=26, quantity=1)])

    result = send(orchestrator, "鸡腿饭改成不辣", state)

    item = _single_order_item(result)
    assert_trace_basics(result, agent="OrderAgent", handler="update_item_option", intent="update_item_option")
    assert item["spicy_level"] == "不辣"
    assert item["quantity"] == 1


def test_order_food_with_multiple_stacked_modifiers(orchestrator):
    result = send(orchestrator, "鸡腿饭少辣，不要葱，米饭多一点")

    item = _single_order_item(result)
    assert item["spicy_level"] == "少辣"
    assert item["exclusions"] == ["葱"]
    assert item["notes"] == "米饭多一点"


def test_multiple_exclusions_are_stacked(orchestrator):
    result = send(orchestrator, "宫保鸡丁不要花生不要辣椒")

    item = _single_order_item(result)
    assert item["name"] == "宫保鸡丁饭"
    assert item["exclusions"] == ["花生", "辣椒"]


def test_exclusions_are_deduplicated(orchestrator):
    result = send(orchestrator, "鸡腿饭不要香菜不要香菜")

    item = _single_order_item(result)
    assert item["exclusions"] == ["香菜"]


def test_remove_exclusion_and_clear_note(orchestrator):
    state = SessionState(
        current_order=[
            OrderItem(
                item_id="chicken_leg_rice",
                name="鸡腿饭",
                price=26,
                quantity=1,
                exclusions=["香菜"],
                notes="汤分开放",
            )
        ]
    )

    result = send(orchestrator, "香菜可以放", state)
    item = _single_order_item(result)
    assert item["exclusions"] == []

    result = send(orchestrator, "备注去掉", result["raw_state"])
    item = _single_order_item(result)
    assert item["notes"] is None


def test_clear_spicy_level_and_replace_note(orchestrator):
    state = SessionState(
        current_order=[
            OrderItem(
                item_id="chicken_leg_rice",
                name="鸡腿饭",
                price=26,
                quantity=1,
                spicy_level="少辣",
                notes="米饭多一点",
            )
        ]
    )

    result = send(orchestrator, "鸡腿饭不用少辣了", state)
    item = _single_order_item(result)
    assert item["spicy_level"] is None
    assert "少辣" not in item["options"]
    assert item["notes"] == "米饭多一点"

    result = send(orchestrator, "鸡腿饭备注改成汤分开放", result["raw_state"])
    item = _single_order_item(result)
    assert item["notes"] == "汤分开放"


def test_ambiguous_modifier_with_multiple_items_clarifies_without_mutation(orchestrator):
    state = SessionState(
        current_order=[
            OrderItem(item_id="chicken_leg_rice", name="鸡腿饭", price=26, quantity=1),
            OrderItem(item_id="cola", name="可乐", price=6, quantity=1),
        ]
    )
    before = state.serializable()

    result = send(orchestrator, "少辣", state)

    assert result["trace"]["finalIntent"] == "context_correction"
    assert state.serializable()["current_order"] == before["current_order"]
    assert "哪一道菜" in result["response"]


def test_empty_note_request_with_multiple_items_clarifies_without_mutation(orchestrator):
    state = SessionState(
        current_order=[
            OrderItem(item_id="chicken_leg_rice", name="鸡腿饭", price=26, quantity=1),
            OrderItem(item_id="cola", name="可乐", price=6, quantity=1),
        ]
    )
    before = state.serializable()

    result = send(orchestrator, "备注一下", state)

    assert result["trace"]["finalIntent"] == "context_correction"
    assert state.serializable()["current_order"] == before["current_order"]
    assert "哪一道菜" in result["response"]


def test_modifier_after_submit_is_locked(orchestrator):
    state = SessionState(
        current_order=[OrderItem(item_id="chicken_leg_rice", name="鸡腿饭", price=26, quantity=1)],
        fulfillment_type="pickup",
        stage="confirming",
    )
    submitted = send(orchestrator, "确认", state)
    assert submitted["state"]["submitted"] is True
    before = state.serializable()

    result = send(orchestrator, "不要香菜", state)

    assert state.serializable() == before
    assert result["trace"]["stateMutationRejectedReason"] == "submitted_order_locked"
    assert "不能继续修改" in result["response"]


def test_existing_remove_and_quantity_update_still_work(orchestrator):
    state = SessionState(
        current_order=[
            OrderItem(item_id="chicken_leg_rice", name="鸡腿饭", price=26, quantity=1),
            OrderItem(item_id="cola", name="可乐", price=6, quantity=1),
        ]
    )

    removed = send(orchestrator, "把可乐删掉", state)
    assert [item["name"] for item in removed["state"]["current_order"]] == ["鸡腿饭"]

    updated = send(orchestrator, "鸡腿饭改成两份", removed["raw_state"])
    item = _single_order_item(updated)
    assert item["name"] == "鸡腿饭"
    assert item["quantity"] == 2


def test_modifier_change_for_missing_order_item_does_not_add_item(orchestrator):
    result = send(orchestrator, "鸡腿饭改成不辣", SessionState())

    assert result["state"]["current_order"] == []
    assert result["trace"]["finalIntent"] == "context_correction"
    assert "订单里没找到" in result["response"]


def test_item_modifier_and_fulfillment_multi_intent_still_passes(orchestrator):
    result = send(orchestrator, "番茄鸡蛋面不要葱，再改成自取")

    assert result["trace"]["finalIntent"] == "composite_intent"
    assert result["state"]["fulfillment_type"] == "pickup"
    item = _single_order_item(result)
    assert item["name"] == "番茄鸡蛋面"
    assert "不要葱" in item["options"]
    assert item["exclusions"] == ["葱"]
