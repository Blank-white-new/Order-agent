from app.state.session_state import SessionState
from .conftest import assert_no_order_mutation, assert_trace_basics, send


def test_menu_overview(orchestrator):
    result = send(orchestrator, "有啥")

    assert_trace_basics(result, agent="MenuAgent", handler="ask_menu", intent="ask_menu")
    assert "饭类" in result["response"]
    assert "鸡腿饭" in result["response"]
    assert_no_order_mutation(result)


def test_ask_no_alcohol_returns_drinks(orchestrator):
    result = send(orchestrator, "有没有酒")

    assert_trace_basics(result, agent="MenuAgent", handler="ask_availability", intent="ask_availability")
    assert "目前没有酒" in result["response"]
    assert "可乐" in result["response"]
    assert_no_order_mutation(result)


def test_ask_drinks_at_delivery_stage_still_menu(orchestrator):
    state = SessionState(stage="collecting_address")
    result = send(orchestrator, "有啥喝的", state)

    assert_trace_basics(result, agent="MenuAgent", handler="ask_category", intent="ask_category")
    assert "饮品" in result["response"]
    assert_no_order_mutation(result)


def test_ask_item_price_does_not_add_order(orchestrator):
    result = send(orchestrator, "鸡腿饭多少钱？")

    assert_trace_basics(result, agent="MenuAgent", handler="ask_price", intent="ask_price")
    assert "26" in result["response"]
    assert result["state"]["current_order"] == []


def test_ask_item_option_does_not_add_order(orchestrator):
    result = send(orchestrator, "鸡腿饭可以不辣吗？")

    assert_trace_basics(result, agent="MenuAgent", handler="ask_option", intent="ask_option")
    assert "不辣" in result["response"]
    assert result["state"]["current_order"] == []


def test_ask_large_option(orchestrator):
    result = send(orchestrator, "牛肉饭有大份吗？")

    assert_trace_basics(result, agent="MenuAgent", handler="ask_option", intent="ask_option")
    assert "大份" in result["response"]
    assert result["state"]["current_order"] == []


def test_ask_order_summary_empty(orchestrator):
    result = send(orchestrator, "我点了什么？")

    assert_trace_basics(result, agent="MenuAgent", handler="ask_order_summary", intent="ask_order_summary")
    assert "还没点" in result["response"]
    assert_no_order_mutation(result)


def test_ask_menu_excluding_rice(orchestrator):
    result = send(orchestrator, "除了饭还有什么？")

    assert_trace_basics(result, agent="MenuAgent", handler="ask_category", intent="ask_category")
    assert "面类" in result["response"]
    assert "饮品" in result["response"]
    assert "牛肉饭" not in result["response"]


def test_ask_specific_categories(orchestrator):
    result = send(orchestrator, "小吃有什么？")

    assert_trace_basics(result, agent="MenuAgent", handler="ask_category", intent="ask_category")
    assert "酸辣土豆丝" in result["response"]
    assert "鸡米花" in result["response"]

    result = send(orchestrator, "有饮品吗")
    assert_trace_basics(result, agent="MenuAgent", handler="ask_availability", intent="ask_availability")
    assert "可乐" in result["response"]


def test_ask_category_group(orchestrator):
    result = send(orchestrator, "主食有什么")

    assert_trace_basics(result, agent="MenuAgent", handler="ask_category_group", intent="ask_category_group")
    assert "饭类" in result["response"]
    assert "面类" in result["response"]
    assert "鸡腿饭" in result["response"]
    assert "番茄鸡蛋面" in result["response"]
    assert_no_order_mutation(result)


def test_ask_item_availability_and_category_price(orchestrator):
    result = send(orchestrator, "有鸡腿饭吗")

    assert_trace_basics(result, agent="MenuAgent", handler="ask_availability", intent="ask_availability")
    assert "鸡腿饭" in result["response"]
    assert "有" in result["response"]

    result = send(orchestrator, "小吃多少钱")
    assert_trace_basics(result, agent="MenuAgent", handler="ask_price", intent="ask_price")
    assert "酸辣土豆丝" in result["response"]
    assert "18" in result["response"]


def test_ask_budget_price_and_cheapest(orchestrator):
    result = send(orchestrator, "30 元以内有什么")

    assert_trace_basics(result, agent="MenuAgent", handler="ask_price", intent="ask_price")
    assert "鸡腿饭" in result["response"]
    assert "30" in result["response"]

    result = send(orchestrator, "最便宜的是哪个")
    assert_trace_basics(result, agent="MenuAgent", handler="ask_price", intent="ask_price")
    assert "可乐" in result["response"]
    assert "6" in result["response"]


def test_ask_ingredient_allergen_and_preference_does_not_order(orchestrator):
    result = send(orchestrator, "鸡腿饭里面有什么")

    assert_trace_basics(result, agent="MenuAgent", handler="ask_ingredient", intent="ask_ingredient")
    assert "鸡腿" in result["response"]
    assert result["state"]["current_order"] == []

    result = send(orchestrator, "对花生过敏，哪些不能点")
    assert_trace_basics(result, agent="MenuAgent", handler="ask_allergen", intent="ask_allergen")
    assert "宫保鸡丁饭" in result["response"]
