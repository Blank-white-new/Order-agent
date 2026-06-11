from app.state.session_state import OrderItem, SessionState
from .conftest import assert_trace_basics, send


def test_order_food_with_non_spicy_preference(orchestrator):
    result = send(orchestrator, "鸡腿饭不辣")

    assert_trace_basics(result, agent="OrderAgent", handler="order_food", intent="order_food")
    assert result["state"]["current_order"][0]["name"] == "鸡腿饭"
    assert "不辣" in result["state"]["current_order"][0]["options"]
    assert "鸡腿饭" in result["response"]


def test_order_food_quantity_and_preference(orchestrator):
    result = send(orchestrator, "鸡腿饭一份，不辣")

    assert_trace_basics(result, agent="OrderAgent", handler="order_food", intent="order_food")
    assert result["state"]["current_order"][0]["quantity"] == 1
    assert "不辣" in result["state"]["current_order"][0]["options"]


def test_recommend_then_explicit_item_order(orchestrator):
    state = send(orchestrator, "推荐")["raw_state"]
    result = send(orchestrator, "鸡腿饭不辣", state)

    assert_trace_basics(result, agent="OrderAgent", handler="order_food", intent="order_food")
    assert result["state"]["current_order"][0]["name"] == "鸡腿饭"


def test_select_first_recommendation(orchestrator):
    state = send(orchestrator, "推荐")["raw_state"]
    result = send(orchestrator, "第一个", state)

    assert_trace_basics(result, agent="OrderAgent", handler="select_recommendation", intent="select_recommendation")
    assert result["state"]["current_order"][0]["name"] == result["trace"]["orderAfter"][0]["name"]


def test_select_second_recommendation_with_no_spicy(orchestrator):
    state = send(orchestrator, "推荐")["raw_state"]
    result = send(orchestrator, "第二个不要辣", state)

    assert_trace_basics(result, agent="OrderAgent", handler="select_recommendation", intent="select_recommendation")
    assert "不辣" in result["state"]["current_order"][0]["options"]


def test_remove_beef_with_empty_order_records_preference(orchestrator):
    result = send(orchestrator, "不要牛肉饭")

    assert_trace_basics(result, agent="OrderAgent", handler="remove_item", intent="remove_item")
    assert result["state"]["current_order"] == []
    assert "牛肉" in result["state"]["preferences"]["avoid"]
    assert "避开牛肉" in result["response"]


def test_remove_beef_with_existing_order(orchestrator):
    state = SessionState(current_order=[OrderItem(item_id="beef_rice", name="牛肉饭", price=28, quantity=1)])
    result = send(orchestrator, "不要牛肉饭", state)

    assert_trace_basics(result, agent="OrderAgent", handler="remove_item", intent="remove_item")
    assert result["state"]["current_order"] == []
    assert "已去掉" in result["response"]


def test_direct_item_name_adds_order(orchestrator):
    result = send(orchestrator, "鸡腿饭")

    assert_trace_basics(result, agent="OrderAgent", handler="order_food", intent="order_food")
    assert result["state"]["current_order"][0]["name"] == "鸡腿饭"


def test_order_food_with_size_and_extra_option(orchestrator):
    result = send(orchestrator, "牛肉饭大份")

    assert_trace_basics(result, agent="OrderAgent", handler="order_food", intent="order_food")
    assert "大份" in result["state"]["current_order"][0]["options"]

    result = send(orchestrator, "番茄鸡蛋面加蛋")
    assert_trace_basics(result, agent="OrderAgent", handler="order_food", intent="order_food")
    assert "加蛋" in result["state"]["current_order"][0]["options"]


def test_order_drink_quantity(orchestrator):
    result = send(orchestrator, "可乐两瓶")

    assert_trace_basics(result, agent="OrderAgent", handler="order_food", intent="order_food")
    assert result["state"]["current_order"][0]["name"] == "可乐"
    assert result["state"]["current_order"][0]["quantity"] == 2


def test_order_multiple_items(orchestrator):
    result = send(orchestrator, "鸡腿饭一份，可乐两瓶")

    assert_trace_basics(result, agent="OrderAgent", handler="order_multiple_items", intent="order_multiple_items")
    names = [item["name"] for item in result["state"]["current_order"]]
    assert names == ["鸡腿饭", "可乐"]
    assert next(item for item in result["state"]["current_order"] if item["name"] == "可乐")["quantity"] == 2


def test_order_multiple_items_with_individual_options(orchestrator):
    result = send(orchestrator, "鸡腿饭不辣，酸辣土豆丝少辣，可乐两瓶")

    assert_trace_basics(result, agent="OrderAgent", handler="order_multiple_items", intent="order_multiple_items")
    order = {item["name"]: item for item in result["state"]["current_order"]}
    assert "不辣" in order["鸡腿饭"]["options"]
    assert "少辣" in order["酸辣土豆丝"]["options"]
    assert order["可乐"]["quantity"] == 2


def test_order_category_items_snacks(orchestrator):
    result = send(orchestrator, "小吃各来一份吧")

    assert_trace_basics(result, agent="OrderAgent", handler="order_category_items", intent="order_category_items")
    assert [item["name"] for item in result["state"]["current_order"]] == ["酸辣土豆丝", "鸡米花"]
    assert "酸辣土豆丝" in result["response"]
    assert "鸡米花" in result["response"]


def test_order_category_items_large_category_requires_confirmation(orchestrator):
    result = send(orchestrator, "饭类各来一份")

    assert_trace_basics(result, agent="OrderAgent", handler="order_category_items", intent="order_category_items")
    assert result["state"]["current_order"] == []
    assert result["state"]["pending_action"]["type"] == "confirm_order_category_items"


def test_update_quantity_and_option(orchestrator):
    state = SessionState(current_order=[OrderItem(item_id="cola", name="可乐", price=6, quantity=1, category="饮品")])
    result = send(orchestrator, "可乐改成两瓶", state)

    assert_trace_basics(result, agent="OrderAgent", handler="update_item_quantity", intent="update_item_quantity")
    assert result["state"]["current_order"][0]["quantity"] == 2

    state = SessionState(current_order=[OrderItem(item_id="chicken_leg_rice", name="鸡腿饭", price=26, quantity=1, category="饭类")])
    result = send(orchestrator, "鸡腿饭不要辣", state)
    assert_trace_basics(result, agent="OrderAgent", handler="update_item_option", intent="update_item_option")
    assert "不辣" in result["state"]["current_order"][0]["options"]


def test_context_index_update_order_item(orchestrator):
    state = SessionState(
        current_order=[
            OrderItem(item_id="chicken_leg_rice", name="鸡腿饭", price=26, quantity=1, category="饭类"),
            OrderItem(item_id="popcorn_chicken", name="鸡米花", price=16, quantity=1, category="小吃"),
        ]
    )
    result = send(orchestrator, "第二个不要辣", state)

    assert_trace_basics(result, agent="OrderAgent", handler="update_item_option", intent="update_item_option")
    assert "不辣" in result["state"]["current_order"][1]["options"]


def test_replace_remove_category_and_clear(orchestrator):
    state = SessionState(current_order=[OrderItem(item_id="beef_rice", name="牛肉饭", price=28, quantity=1, category="饭类")])
    result = send(orchestrator, "牛肉饭换成鸡腿饭", state)

    assert_trace_basics(result, agent="OrderAgent", handler="replace_item", intent="replace_item")
    assert result["state"]["current_order"][0]["name"] == "鸡腿饭"

    state = SessionState(
        current_order=[
            OrderItem(item_id="sour_spicy_potato", name="酸辣土豆丝", price=18, quantity=1, category="小吃"),
            OrderItem(item_id="popcorn_chicken", name="鸡米花", price=16, quantity=1, category="小吃"),
        ]
    )
    result = send(orchestrator, "小吃不要了", state)
    assert_trace_basics(result, agent="OrderAgent", handler="remove_category_items", intent="remove_category_items")
    assert result["state"]["pending_action"]["type"] == "confirm_remove_category_items"

    result = send(orchestrator, "清空订单", state)
    assert_trace_basics(result, agent="OrderAgent", handler="clear_order", intent="clear_order")
    assert result["state"]["current_order"] == []
