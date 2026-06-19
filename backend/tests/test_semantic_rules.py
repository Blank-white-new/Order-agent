from app.agents.semantic_rules import (
    detect_category_group_query,
    detect_composite_intent,
    detect_conditional_order,
    detect_subjective_ranking_query,
    extract_address_candidate,
    extract_multiple_items,
    extract_preferences,
    normalize_text,
    parse_chinese_number,
    parse_quantity,
    parse_quantity_each,
    parse_unit,
    resolve_context_reference,
)
from app.services.menu_service import MenuService
from app.state.session_state import DeliveryAddressCandidate, OrderItem, SessionState


def test_normalize_text_removes_spaces_and_punctuation():
    assert normalize_text(" 鸡腿饭 不辣，再来瓶可乐？ ") == "鸡腿饭不辣再来瓶可乐"


def test_parse_chinese_number_and_quantity_units():
    assert parse_chinese_number("两") == 2
    assert parse_chinese_number("俩") == 2
    assert parse_quantity("可乐两瓶") == 2
    assert parse_quantity("鸡腿饭来俩") == 2
    assert parse_quantity("改成2份") == 2
    assert parse_unit("柠檬茶一杯") == "杯"
    assert parse_quantity_each("饮品都来两瓶") == 2
    assert parse_quantity_each("每样一份") == 1


def test_detect_category_group_and_subjective_ranking():
    assert detect_category_group_query("主食有什么") == {"group": "主食", "categories": ["饭类", "面类"]}
    assert detect_category_group_query("有啥喝的") == {"group": "喝的", "categories": ["饮品"]}

    ranked = detect_subjective_ranking_query("饭类哪个最好吃", MenuService())
    assert ranked["is_ranking"] is True
    assert ranked["category"] == "饭类"
    assert ranked["sales_claim_requested"] is False

    popular = detect_subjective_ranking_query("哪个卖得好", MenuService())
    assert popular["is_ranking"] is True
    assert popular["sales_claim_requested"] is True

    hot = detect_subjective_ranking_query("热门菜有啥", MenuService())
    assert hot["is_ranking"] is True
    assert hot["sales_claim_requested"] is False

    signature = detect_subjective_ranking_query("招牌菜是啥", MenuService())
    assert signature["is_ranking"] is True
    assert signature["sales_claim_requested"] is False


def test_extract_preferences_and_multiple_items():
    menu = MenuService()
    preferences = extract_preferences("推荐个清淡的，不要牛肉，30以内")

    assert "清淡" in preferences["options"]
    assert "牛肉" in preferences["avoid"]
    assert preferences["budget"] == 30

    specs = extract_multiple_items("鸡腿饭不辣，酸辣土豆丝少辣，可乐两瓶", menu)
    by_name = {spec["item_name"]: spec for spec in specs}
    assert by_name["鸡腿饭"]["options"] == ["不辣"]
    assert by_name["酸辣土豆丝"]["options"] == ["少辣"]
    assert by_name["可乐"]["quantity"] == 2
    assert by_name["可乐"]["unit"] == "瓶"


def test_detect_composite_intent_children_are_ordered():
    menu = MenuService()
    composite = detect_composite_intent("鸡腿饭不辣，再来瓶可乐，配送到中山大学南校园要多久", menu)

    assert composite is not None
    assert [child["intent"] for child in composite["children"]] == [
        "order_food",
        "order_food",
        "ask_delivery_eta",
    ]
    assert composite["children"][0]["entities"]["item_name"] == "鸡腿饭"
    assert composite["children"][1]["entities"]["item_name"] == "可乐"
    assert composite["children"][1]["entities"]["quantity"] == 1
    assert composite["children"][2]["entities"]["address"] == "中山大学南校园"


def test_detect_conditional_order_structured_pending_action():
    menu = MenuService()
    conditional = detect_conditional_order("鸡腿饭多少钱？如果不贵就来一份", menu)

    assert conditional is not None
    assert conditional["condition"]["type"] == "price_threshold"
    assert conditional["fact_result"]["item_name"] == "鸡腿饭"
    assert conditional["fact_result"]["price"] == 26
    assert conditional["proposed_action"]["intent"] == "order_food"
    assert conditional["requires_confirmation"] is True


def test_extract_address_and_context_reference_resolution():
    assert extract_address_candidate("配送到中山大学南校园要多久") == "中山大学南校园"

    state = SessionState(
        last_recommendations=[{"name": "鸡腿饭", "id": "chicken_leg_rice"}],
        current_order=[OrderItem(item_id="cola", name="可乐", price=6, quantity=1, category="饮品")],
        pending_delivery_address_candidate=DeliveryAddressCandidate(
            raw="中山大学南校园",
            normalized="中山大学南校园",
            source="eta_question",
            confidence=0.95,
        ),
    )
    assert resolve_context_reference("第一个", state)["kind"] == "recommendation"
    assert resolve_context_reference("刚才那个不要了", state)["kind"] == "order_item"
    assert resolve_context_reference("这个地址能送到吗", state)["kind"] == "address"
