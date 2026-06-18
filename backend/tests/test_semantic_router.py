import pytest

from app.agents.semantic_router import SemanticRouterAgent


@pytest.mark.parametrize(
    ("message", "intent", "is_question", "should_mutate"),
    [
        ("有啥", "ask_menu", True, False),
        ("有啥？", "ask_menu", True, False),
        ("都有啥呀", "ask_menu", True, False),
        ("菜单有啥", "ask_menu", True, False),
        ("有什么吃的", "ask_menu", True, False),
        ("有没有酒", "ask_availability", True, False),
        ("有啥喝的", "ask_category", True, False),
        ("有饮品吗", "ask_availability", True, False),
        ("鸡腿饭多少钱？", "ask_price", True, False),
        ("鸡腿饭可以不辣吗？", "ask_option", True, False),
        ("鸡腿饭不辣", "order_food", False, True),
        ("中山大学南校园要送多久？", "ask_delivery_eta", True, False),
        ("到中山大学南校园配送费多少？", "ask_delivery_fee", True, False),
        ("中山大学南校园能送吗？", "ask_deliverability", True, False),
        ("刚才啥也没点啊", "context_correction", False, False),
        ("推荐", "ask_recommendation", True, False),
        ("饭，除了饭还有什么？", "ask_category", True, False),
    ],
)
def test_router_recognizes_required_phrases(message, intent, is_question, should_mutate):
    result = SemanticRouterAgent().interpret(message)

    assert result.intent == intent
    assert result.source in {"rule", "deterministic"}
    assert result.confidence >= 0.85
    assert result.is_question is is_question
    assert result.should_mutate_order is should_mutate


def test_delivery_fee_wins_over_general_price_language():
    result = SemanticRouterAgent().interpret("到中山大学南校园配送费多少？")

    assert result.intent == "ask_delivery_fee"
    assert result.entities["address"] == "中山大学南校园"


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("你们这有什么吃的", "ask_menu"),
        ("看菜单", "ask_menu"),
        ("饭有什么", "ask_category"),
        ("小吃有什么？", "ask_category"),
        ("有啥喝的", "ask_category"),
        ("除了饭还有什么", "ask_category"),
        ("饭以外还有啥", "ask_category"),
        ("有鸡腿饭吗", "ask_availability"),
        ("牛肉面还有吗", "ask_availability"),
        ("酸辣土豆丝卖完了吗", "ask_availability"),
        ("小吃多少钱", "ask_price"),
        ("饭类价格", "ask_price"),
        ("最便宜的是哪个", "ask_price"),
        ("30 元以内有什么", "ask_price"),
        ("鸡腿饭里面有什么", "ask_ingredient"),
        ("牛肉面有香菜吗", "ask_ingredient"),
        ("对花生过敏，哪些不能点", "ask_allergen"),
        ("我不吃牛肉，有什么", "ask_recommendation_by_preference"),
        ("有没有不辣的", "ask_recommendation_by_preference"),
        ("现在多少钱了", "ask_order_summary"),
    ],
)
def test_router_menu_information_matrix(message, intent):
    result = SemanticRouterAgent().interpret(message)

    assert result.intent == intent
    assert result.source in {"rule", "deterministic"}
    assert result.confidence >= 0.8
    assert result.should_mutate_order is False


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("不知道吃啥", "ask_recommendation"),
        ("你看着办", "ask_recommendation"),
        ("来个好吃的", "ask_recommendation"),
        ("有啥推荐的", "ask_recommendation"),
        ("有什么推荐", "ask_recommendation"),
        ("有啥好推荐的", "ask_recommendation"),
        ("推荐一下", "ask_recommendation"),
        ("推荐点好吃的", "ask_recommendation"),
        ("推荐个菜", "ask_recommendation"),
        ("推荐几个菜", "ask_recommendation"),
        ("你推荐什么", "ask_recommendation"),
        ("你有什么推荐", "ask_recommendation"),
        ("有啥好吃的", "ask_recommendation"),
        ("随便推荐一个", "ask_recommendation"),
        ("随便来个好吃的", "ask_recommendation"),
        ("推荐个饭", "ask_recommendation_by_category"),
        ("小吃推荐一下", "ask_recommendation_by_category"),
        ("来个清淡点的", "ask_recommendation_by_preference"),
        ("不辣的", "ask_recommendation_by_preference"),
        ("便宜点的", "ask_recommendation_by_preference"),
        ("30 元以内推荐", "ask_recommendation_by_budget"),
        ("快一点的", "ask_recommendation_by_speed"),
        ("换一个", "ask_recommendation"),
        ("还有别的吗", "ask_recommendation"),
    ],
)
def test_router_recommendation_matrix(message, intent):
    result = SemanticRouterAgent().interpret(message)

    assert result.intent == intent
    assert result.confidence >= 0.8
    assert result.source in {"rule", "deterministic"}
    assert result.should_mutate_order is False


@pytest.mark.parametrize(
    ("message", "intent", "should_mutate"),
    [
        ("鸡腿饭", "order_food", True),
        ("来一份鸡腿饭", "order_food", True),
        ("可乐两瓶", "order_food", True),
        ("我要鸡腿饭和可乐", "order_multiple_items", True),
        ("鸡腿饭一份，可乐两瓶", "order_multiple_items", True),
        ("牛肉饭和鸡米花各一份", "order_multiple_items", True),
        ("小吃各来一份", "order_category_items", True),
        ("小吃各来一份吧", "order_category_items", True),
        ("饮品都来两瓶", "order_category_items", True),
        ("饭类各来一份", "order_category_items", True),
        ("鸡腿饭改成大份", "update_item_option", True),
        ("可乐改成两瓶", "update_item_quantity", True),
        ("牛肉饭换成鸡腿饭", "replace_item", True),
        ("小吃不要了", "remove_category_items", True),
        ("饮品都不要了", "remove_category_items", True),
        ("清空订单", "clear_order", True),
        ("全部不要了", "clear_order", True),
    ],
)
def test_router_ordering_and_modification_matrix(message, intent, should_mutate):
    result = SemanticRouterAgent().interpret(message)

    assert result.intent == intent
    assert result.should_mutate_order is should_mutate
    assert result.confidence >= 0.8


@pytest.mark.parametrize(
    ("message", "expected_item"),
    [
        ("宫保鸡丁来一份吧", "宫保鸡丁饭"),
        ("黑胶牛肉饭来一份", "黑椒牛肉饭"),
        ("黑角牛肉饭来一份", "黑椒牛肉饭"),
    ],
)
def test_router_common_alias_orders_use_specific_menu_item(message, expected_item):
    result = SemanticRouterAgent().interpret(message)

    assert result.intent == "order_food"
    assert result.entities["item_name"] == expected_item
    assert result.should_mutate_order is True


@pytest.mark.parametrize("message", ["中山大学鸡腿饭店旁边", "鸡腿饭餐厅楼上", "饭堂三楼"])
def test_router_address_like_text_with_menu_fragments_does_not_order(message):
    result = SemanticRouterAgent().interpret(message)

    assert result.intent == "fallback"
    assert result.should_mutate_order is False


@pytest.mark.parametrize(
    ("message", "expected_item"),
    [
        ("送到中山大学，鸡腿饭来一份", "鸡腿饭"),
        ("送到中山大学，宫保鸡丁来一份", "宫保鸡丁饭"),
    ],
)
def test_router_mixed_address_and_order_uses_only_evidenced_order_fragment(message, expected_item):
    result = SemanticRouterAgent().interpret(message)

    assert result.intent == "composite_intent"
    children = result.entities["children"]
    assert children[0]["intent"] == "order_food"
    assert children[0]["entities"]["item_name"] == expected_item
    assert children[1]["intent"] == "replace_delivery_candidate"
    assert children[1]["entities"]["address"] == "中山大学"


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("配送", "provide_fulfillment_slot"),
        ("外卖", "provide_fulfillment_slot"),
        ("自取", "provide_fulfillment_slot"),
        ("到店取", "provide_fulfillment_slot"),
        ("电话 13812345678", "provide_phone"),
        ("手机号是 13812345678", "provide_phone"),
        ("配送要多久", "ask_delivery_eta"),
        ("多久能送到", "ask_delivery_eta"),
        ("送到学校东门多少钱", "ask_delivery_fee"),
        ("到中山大学南校园多少钱", "ask_delivery_fee"),
        ("学校东门能配送吗", "ask_deliverability"),
        ("这个地址能送到吗", "ask_deliverability"),
    ],
)
def test_router_delivery_matrix(message, intent):
    result = SemanticRouterAgent().interpret(message)

    assert result.intent == intent
    assert result.confidence >= 0.8


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("第二个不要辣", "context_reference_resolution"),
        ("第一个改成大份", "context_reference_resolution"),
        ("刚才那个不要了", "context_reference_resolution"),
        ("这些都要", "context_reference_resolution"),
        ("我不是要这个", "context_correction"),
    ],
)
def test_router_context_references_and_corrections(message, intent):
    result = SemanticRouterAgent().interpret(message)

    assert result.intent == intent
    assert result.confidence >= 0.75


def test_router_explicit_conflicts():
    router = SemanticRouterAgent()

    assert router.interpret("小吃有什么？").intent == "ask_category"
    assert router.interpret("小吃推荐一下").intent == "ask_recommendation_by_category"
    assert router.interpret("小吃各来一份").intent == "order_category_items"
    assert router.interpret("鸡腿饭多少钱？").intent == "ask_price"
    assert router.interpret("鸡腿饭可以不辣吗？").intent == "ask_option"
    assert router.interpret("鸡腿饭不辣").intent == "order_food"
    assert router.interpret("配送费多少？").intent == "ask_delivery_fee"
    assert router.interpret("不要辣").intent in {"ask_recommendation_by_preference", "update_item_option"}
    assert router.interpret("不要辣").intent != "cancel"


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("主食有什么", "ask_category_group"),
        ("正餐有什么", "ask_category_group"),
        ("主食", "ask_category_group"),
        ("喝的", "ask_category"),
        ("饭类哪个最好吃", "ask_recommendation_by_category_ranked"),
        ("饭类哪个推荐", "ask_recommendation_by_category_ranked"),
        ("饮品哪个好喝", "ask_recommendation_by_category_ranked"),
        ("主食哪个推荐", "ask_recommendation_by_category_ranked"),
        ("哪个好吃", "ask_recommendation_by_category_ranked"),
        ("哪个比较好吃", "ask_recommendation_by_category_ranked"),
        ("哪个最好吃", "ask_recommendation_by_category_ranked"),
        ("招牌菜是啥", "ask_recommendation_by_category_ranked"),
        ("招牌菜是什么", "ask_recommendation_by_category_ranked"),
        ("热门菜有啥", "ask_recommendation_by_category_ranked"),
        ("热门推荐", "ask_recommendation_by_category_ranked"),
        ("哪个卖得好", "ask_recommendation_by_category_ranked"),
        ("你帮我选一个", "ask_recommendation_by_category_ranked"),
        ("清淡点", "ask_recommendation_by_preference"),
        ("便宜点", "ask_recommendation_by_preference"),
        ("快点", "ask_recommendation_by_speed"),
        ("随便", "ask_recommendation"),
    ],
)
def test_router_short_group_and_subjective_ranking(message, intent):
    result = SemanticRouterAgent().interpret(message)

    assert result.intent == intent
    assert result.confidence >= 0.8
    assert result.source in {"rule", "deterministic"}


def test_router_detects_composite_before_order_multiple():
    result = SemanticRouterAgent().interpret("鸡腿饭不辣，再来瓶可乐，配送到中山大学南校园要多久")

    assert result.intent == "composite_intent"
    assert result.should_mutate_order is True
    assert [child["intent"] for child in result.entities["children"]] == [
        "order_food",
        "order_food",
        "ask_delivery_eta",
    ]


def test_router_detects_conditional_order_before_plain_price():
    result = SemanticRouterAgent().interpret("鸡腿饭多少钱？如果不贵就来一份")

    assert result.intent == "conditional_order"
    assert result.should_mutate_order is False
    assert result.entities["conditionalDecision"]["fact_result"]["price"] == 26
    assert result.entities["conditionalDecision"]["requires_confirmation"] is True


def test_router_new_conflict_negative_cases():
    router = SemanticRouterAgent()

    assert router.interpret("小吃有什么").intent == "ask_category"
    assert router.interpret("小吃推荐一下").intent == "ask_recommendation_by_category"
    assert router.interpret("小吃各来一份").intent == "order_category_items"
    assert router.interpret("鸡腿饭多少钱").intent == "ask_price"
    assert router.interpret("鸡腿饭不辣").intent == "order_food"
    assert router.interpret("鸡腿饭可以不辣吗").intent == "ask_option"
    assert router.interpret("不要辣").intent != "cancel"
    assert router.interpret("配送费多少").intent == "ask_delivery_fee"
    assert router.interpret("蓝色的云能不能快一点").intent != "ask_recommendation_by_speed"
