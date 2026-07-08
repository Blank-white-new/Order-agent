from __future__ import annotations

import pytest

from app.agents.semantic_evidence import (
    detect_reference_domain,
    has_add_action_evidence,
    has_remove_action_evidence,
    is_non_ordering_statement,
)
from app.state.session_state import SessionState
from .conftest import send


def _items(state: SessionState) -> list[tuple[str, int]]:
    return [(item.name, item.quantity) for item in state.current_order]


def _seed(orchestrator, *messages: str) -> SessionState:
    state = SessionState()
    for message in messages:
        send(orchestrator, message, state)
    return state


def test_semantic_evidence_helpers_separate_interest_from_actions():
    assert is_non_ordering_statement("鸡腿饭听起来不错") is True
    assert has_add_action_evidence("来一份鸡腿饭") is True
    assert has_remove_action_evidence("可乐不要了") is True
    assert detect_reference_domain("第一个不要了", True, True) == "order"
    assert detect_reference_domain("推荐的第一个来一份", True, True) == "recommendation"


@pytest.mark.parametrize(
    "message",
    [
        "鸡腿饭听起来不错",
        "黑椒牛肉饭好像不错",
        "可乐看起来可以",
        "我看看鸡腿饭",
    ],
)
def test_non_ordering_statements_do_not_add_items(orchestrator, message):
    state = SessionState()
    result = send(orchestrator, message, state)

    assert state.current_order == []
    assert result["trace"]["finalIntent"] == "context_correction"
    assert result["trace"]["semanticEvidenceReason"] == "non_ordering_statement"
    assert "想点一份" in result["response"]


def test_item_question_does_not_add_item(orchestrator):
    state = SessionState()
    result = send(orchestrator, "鸡腿饭有优惠吗", state)

    assert state.current_order == []
    assert result["trace"]["finalIntent"] == "ask_availability"
    assert result["trace"]["stateMutationAllowed"] is True
    assert result["trace"]["orderBefore"] == result["trace"]["orderAfter"]


@pytest.mark.parametrize(
    ("message", "expected_quantity"),
    [
        ("来一份鸡腿饭", 1),
        ("我要鸡腿饭", 1),
        ("鸡腿饭加一份", 1),
        ("鸡腿饭两份", 2),
        ("给我来个鸡腿饭", 1),
    ],
)
def test_explicit_ordering_still_adds_items(orchestrator, message, expected_quantity):
    state = SessionState()
    result = send(orchestrator, message, state)

    assert result["trace"]["finalIntent"] == "order_food"
    assert _items(state) == [("鸡腿饭", expected_quantity)]


def test_mixed_add_and_remove_is_atomic_enough(orchestrator):
    state = _seed(orchestrator, "可乐来一份")
    result = send(orchestrator, "鸡腿饭来一份，可乐不要了", state)

    assert result["trace"]["finalIntent"] == "composite_intent"
    assert _items(state) == [("鸡腿饭", 1)]
    assert [child["intent"] for child in result["trace"]["compositeChildren"]] == ["order_food", "remove_item"]


def test_mixed_add_quantity_and_remove(orchestrator):
    state = _seed(orchestrator, "牛肉饭来一份")
    send(orchestrator, "鸡腿饭两份，再把牛肉饭删掉", state)

    assert _items(state) == [("鸡腿饭", 2)]


def test_vague_add_with_info_query_clarifies_without_order_mutation(orchestrator):
    state = SessionState()
    result = send(orchestrator, "来份面，再问一下配送费", state)

    assert state.current_order == []
    assert result["trace"]["finalIntent"] == "context_correction"
    assert result["trace"]["semanticEvidenceReason"] == "vague_order_with_question"


def test_modify_by_order_index_with_total_query(orchestrator):
    state = _seed(orchestrator, "鸡腿饭一份，可乐一瓶")
    result = send(orchestrator, "把第一份改成两份，然后看下总价", state)

    assert result["trace"]["finalIntent"] == "update_item_quantity"
    assert _items(state) == [("鸡腿饭", 2), ("可乐", 1)]


@pytest.mark.parametrize("message", ["推荐的第一个来一份", "刚推荐的第一个来一份"])
def test_recommendation_ordinal_adds_recommended_item(orchestrator, message):
    state = _seed(orchestrator, "推荐个主食")
    result = send(orchestrator, message, state)

    assert result["trace"]["finalIntent"] == "select_recommendation"
    assert result["trace"]["referenceDomain"] == "recommendation"
    assert _items(state) == [("鸡腿饭", 1)]


def test_order_ordinal_remove_and_update_use_order_domain(orchestrator):
    state = _seed(orchestrator, "鸡腿饭一份，可乐一瓶")

    remove_result = send(orchestrator, "订单里第一个不要了", state)
    assert remove_result["trace"]["referenceDomain"] == "order"
    assert _items(state) == [("可乐", 1)]

    state = _seed(orchestrator, "鸡腿饭一份，可乐一瓶")
    update_result = send(orchestrator, "第一份改成两份", state)
    assert update_result["trace"]["referenceDomain"] == "order"
    assert _items(state) == [("鸡腿饭", 2), ("可乐", 1)]


def test_bare_ordinal_remove_prefers_order_over_recommendation(orchestrator):
    state = _seed(orchestrator, "推荐个主食", "鸡腿饭一份")
    result = send(orchestrator, "第一个不要了", state)

    assert result["trace"]["finalIntent"] == "remove_item"
    assert result["trace"]["referenceDomain"] == "order"
    assert state.current_order == []


@pytest.mark.parametrize(
    ("initial", "message", "expected"),
    [
        (["鸡腿饭一份"], "刚才那个换成可乐", [("可乐", 1)]),
        (["鸡腿饭一份"], "刚加的换成番茄鸡蛋面", [("番茄鸡蛋面", 1)]),
        (["鸡腿饭一份"], "那份鸡腿饭换成牛肉饭", [("牛肉饭", 1)]),
    ],
)
def test_natural_replace_removes_old_item(orchestrator, initial, message, expected):
    state = _seed(orchestrator, *initial)
    result = send(orchestrator, message, state)

    assert result["trace"]["finalIntent"] == "replace_item"
    assert _items(state) == expected


def test_ambiguous_replace_reference_clarifies(orchestrator):
    state = _seed(orchestrator, "鸡腿饭一份，可乐一瓶")
    before = _items(state)
    result = send(orchestrator, "这个换成鸡腿饭", state)

    assert result["trace"]["finalIntent"] == "context_correction"
    assert result["trace"]["semanticEvidenceReason"] == "ambiguous_order_reference"
    assert _items(state) == before


@pytest.mark.parametrize(
    ("message", "address"),
    [
        ("送到中山大学南校园，电话是 13800000000", "中山大学南校园"),
        ("地址是大学城一号宿舍楼，手机号 13800000000", "大学城一号宿舍楼"),
        ("我要配送到中山大学，电话 13800000000", "中山大学"),
    ],
)
def test_address_and_phone_are_collected_together(orchestrator, message, address):
    state = SessionState()
    result = send(orchestrator, message, state)

    assert result["trace"]["finalIntent"] == "composite_intent"
    assert state.official_delivery_address == address
    assert state.phone == "13800000000"
    assert state.current_order == []


def test_address_phone_and_add_item_multi_intent(orchestrator):
    state = SessionState()
    send(orchestrator, "送到中山大学南校园，再来一份可乐", state)

    assert state.official_delivery_address == "中山大学南校园"
    assert state.phone is None
    assert _items(state) == [("可乐", 1)]


@pytest.mark.parametrize(
    "message",
    [
        "黑椒牛肉饭有优惠吗",
        "鸡腿饭多少钱",
        "可乐还有吗",
        "牛肉饭辣吗",
        "配送费多少",
        "多久送到",
        "能送到中山大学吗",
        "菜单里有什么饭",
    ],
)
def test_questions_do_not_mutate_order(orchestrator, message):
    state = SessionState()
    result = send(orchestrator, message, state)

    assert state.current_order == []
    assert result["trace"]["orderBefore"] == result["trace"]["orderAfter"]
    assert result["trace"]["finalIntent"].startswith("ask_")
