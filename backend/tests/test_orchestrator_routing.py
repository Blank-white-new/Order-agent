import pytest

from app.agents.orchestrator import INTENT_HANDLER_MAP, OrchestratorAgent
from app.models.schemas import Interpretation
from app.state.session_state import SessionState


REQUIRED_INTENTS = {
    "ask_menu",
    "ask_category",
    "ask_category_group",
    "ask_availability",
    "ask_price",
    "ask_option",
    "ask_ingredient",
    "ask_allergen",
    "ask_order_summary",
    "ask_recommendation",
    "ask_recommendation_by_category",
    "ask_recommendation_by_category_ranked",
    "ask_recommendation_by_preference",
    "ask_recommendation_by_budget",
    "ask_recommendation_by_speed",
    "order_food",
    "order_multiple_items",
    "order_category_items",
    "order_category_group_items",
    "composite_intent",
    "conditional_order",
    "select_recommendation",
    "order_by_preference",
    "update_item_option",
    "update_item_quantity",
    "remove_item",
    "remove_category_items",
    "replace_item",
    "clear_order",
    "provide_fulfillment_slot",
    "provide_delivery_address",
    "provide_phone",
    "ask_delivery_eta",
    "ask_delivery_fee",
    "ask_deliverability",
    "confirm_delivery_candidate",
    "reject_delivery_candidate",
    "replace_delivery_candidate",
    "conditional_fulfillment",
    "context_correction",
    "context_reference_resolution",
    "confirm",
    "cancel",
    "smalltalk",
    "fallback",
}


def test_every_required_intent_has_handler_mapping():
    assert REQUIRED_INTENTS <= set(INTENT_HANDLER_MAP)
    for intent, mapping in INTENT_HANDLER_MAP.items():
        assert mapping["agent"]
        assert mapping["handler"]


@pytest.mark.parametrize(
    ("intent", "agent", "handler"),
    [
        ("ask_category", "MenuAgent", "ask_category"),
        ("ask_ingredient", "MenuAgent", "ask_ingredient"),
        ("ask_recommendation_by_category", "RecommendationAgent", "ask_recommendation_by_category"),
        ("order_multiple_items", "OrderAgent", "order_multiple_items"),
        ("order_category_items", "OrderAgent", "order_category_items"),
        ("remove_category_items", "OrderAgent", "remove_category_items"),
        ("replace_item", "OrderAgent", "replace_item"),
        ("confirm_delivery_candidate", "DeliveryAgent", "confirm_pending_address"),
        ("clear_order", "OrderAgent", "clear_order"),
    ],
)
def test_dispatch_uses_mapping(intent, agent, handler):
    orchestrator = OrchestratorAgent()
    state = SessionState()
    interpretation = Interpretation(intent=intent, confidence=0.9, source="rule")

    result = orchestrator._dispatch(interpretation, state)

    assert result["agent"] == agent
    assert result["handler"] == handler


def test_composite_intent_executes_children_independently(orchestrator):
    result = orchestrator.handle_user_message("鸡腿饭不辣，再来瓶可乐，配送到中山大学南校园要多久", SessionState())

    trace = result["trace"]
    assert trace["finalIntent"] == "composite_intent"
    assert trace["selectedAgent"] == "OrchestratorAgent"
    assert trace["selectedHandler"] == "composite_intent"
    assert trace["fallbackUsed"] is False
    assert [child["intent"] for child in trace["compositeChildren"]] == [
        "order_food",
        "order_food",
        "ask_delivery_eta",
    ]
    assert all(child["stateMutationAllowed"] for child in trace["compositeChildren"])
    assert [item["name"] for item in result["state"]["current_order"]] == ["鸡腿饭", "可乐"]
    assert result["state"]["official_delivery_address"] is None
    assert result["state"]["pending_delivery_address_candidate"]["normalized"] == "中山大学南校园"


def test_conditional_order_sets_structured_pending_action(orchestrator):
    result = orchestrator.handle_user_message("鸡腿饭多少钱？如果不贵就来一份", SessionState())

    trace = result["trace"]
    assert trace["finalIntent"] == "conditional_order"
    assert trace["selectedAgent"] == "OrchestratorAgent"
    assert trace["selectedHandler"] == "conditional_order"
    assert result["state"]["current_order"] == []
    assert result["state"]["pending_action"]["type"] == "conditional_order"
    assert result["state"]["pending_action"]["condition"]["type"] == "price_threshold"
    assert trace["conditionalDecision"]["fact_result"]["price"] == 26
    assert "26" in result["response"]


def test_smalltalk_preserves_pending_delivery_candidate(orchestrator):
    state = orchestrator.handle_user_message("中山大学南校园要送多久", SessionState())["raw_state"]
    result = orchestrator.handle_user_message("哈哈", state)

    assert result["trace"]["finalIntent"] in {"smalltalk", "fallback"}
    assert result["state"]["pending_delivery_address_candidate"]["normalized"] == "中山大学南校园"


def test_context_repair_rolls_back_recent_unconfirmed_mutation(orchestrator):
    state = orchestrator.handle_user_message("鸡腿饭不辣", SessionState())["raw_state"]
    result = orchestrator.handle_user_message("我只是问一下", state)

    assert result["trace"]["finalIntent"] == "context_correction"
    assert result["trace"]["rollbackApplied"] is True
    assert result["trace"]["rolledBackFields"] == ["current_order"]
    assert result["state"]["current_order"] == []


def test_context_repair_does_not_rollback_confirmed_mutation(orchestrator):
    state = SessionState(current_order=[])
    state.last_mutation_snapshot = {
        "mutation_id": "m-1",
        "trigger_user_message": "确认",
        "agent_action": "submit_order",
        "changed_fields": ["submitted"],
        "before": {"current_order": []},
        "after": {"submitted": True},
        "confirmed": True,
    }
    result = orchestrator.handle_user_message("你别乱加", state)

    assert result["trace"]["rollbackApplied"] is False
    assert result["state"]["last_mutation_snapshot"]["confirmed"] is True


def test_reverse_mutation_invariants_for_conflicting_inputs(orchestrator):
    result = orchestrator.handle_user_message("鸡腿饭多少钱", SessionState())
    assert result["trace"]["selectedAgent"] == "MenuAgent"
    assert result["trace"]["finalIntent"] == "ask_price"
    assert result["state"]["current_order"] == []

    result = orchestrator.handle_user_message("鸡腿饭可以不辣吗", SessionState())
    assert result["trace"]["selectedAgent"] == "MenuAgent"
    assert result["trace"]["finalIntent"] == "ask_option"
    assert result["state"]["current_order"] == []

    result = orchestrator.handle_user_message("中山大学南校园要送多久", SessionState())
    assert result["trace"]["finalIntent"] == "ask_delivery_eta"
    assert result["state"]["official_delivery_address"] is None
    assert result["state"]["pending_delivery_address_candidate"]["normalized"] == "中山大学南校园"

    result = orchestrator.handle_user_message("主食有什么", SessionState())
    assert result["trace"]["finalIntent"] == "ask_category_group"
    assert result["trace"]["fallbackUsed"] is False

    result = orchestrator.handle_user_message("饭类各来一份", SessionState())
    assert result["trace"]["finalIntent"] == "order_category_items"
    assert result["trace"]["selectedHandler"] == "order_category_items"
